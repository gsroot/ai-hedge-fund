#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PREDICT_SCRIPTS = PROJECT_ROOT / ".agents" / "skills" / "predict" / "scripts"
if str(PREDICT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PREDICT_SCRIPTS))

from data_fetcher import get_prices  # noqa: E402


VALID_SENTIMENTS = {"positive", "negative", "neutral"}
DIRECTION = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
HORIZON_NEUTRAL_BANDS = {1: 0.01, 5: 0.025, 20: 0.05}


def load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def article_date(value: Any) -> pd.Timestamp:
    return pd.Timestamp(str(value)[:10]).normalize()


def task_articles(task_payload: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for task in task_payload.get("tasks", []):
        ticker = str(task.get("ticker") or "")
        company_name = str(task.get("company_name") or ticker)
        for article in task.get("articles", []):
            records.append(
                {
                    "ticker": ticker,
                    "company_name": company_name,
                    "article_index": int(article["article_index"]),
                    "date": article_date(article["date"]),
                    "headline": str(article.get("headline") or ""),
                    "link": str(article.get("link") or ""),
                    "content_type": str(article.get("content_type") or "unknown"),
                }
            )
    return records


def expand_annotations(
    task_payload: dict[str, Any], annotation_payload: dict[str, Any]
) -> list[dict[str, Any]]:
    if annotation_payload.get("analysis_date") != task_payload.get("analysis_date"):
        raise ValueError("Historical task and annotation dates differ")
    default = annotation_payload.get("default") or {}
    overrides = {
        (str(item["ticker"]), int(item["article_index"])): item
        for item in annotation_payload.get("overrides", [])
    }
    records = []
    used = set()
    for article in task_articles(task_payload):
        key = (article["ticker"], article["article_index"])
        annotation = overrides.get(key, default)
        sentiment = str(annotation.get("sentiment") or "")
        confidence = float(annotation.get("confidence", -1))
        if sentiment not in VALID_SENTIMENTS or not 0 <= confidence <= 100:
            raise ValueError(f"Invalid historical annotation: {key}")
        if key in overrides:
            used.add(key)
        records.append(
            {
                **article,
                "sentiment": sentiment,
                "confidence": confidence,
                "reasoning": str(annotation.get("reasoning") or ""),
            }
        )
    unused = sorted(set(overrides) - used)
    if unused:
        raise ValueError(f"Unused historical overrides: {unused}")
    return records


def classification_records(
    task_payload: dict[str, Any], classification_payload: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    articles = {
        (item["ticker"], item["article_index"]): item
        for item in task_articles(task_payload)
    }
    issues: list[str] = []
    records: list[dict[str, Any]] = []
    seen = set()
    if classification_payload.get("analysis_date") != task_payload.get("analysis_date"):
        issues.append("classification_analysis_date_mismatch")
    if classification_payload.get("source") != "active_skill_llm":
        issues.append("classification_source_mismatch")
    for result in classification_payload.get("results", []):
        ticker = str(result.get("ticker") or "")
        for item in result.get("classifications", []):
            key = (ticker, int(item.get("article_index", -1)))
            if key in seen:
                issues.append(f"duplicate_classification:{ticker}:{key[1]}")
                continue
            seen.add(key)
            article = articles.get(key)
            if article is None:
                issues.append(f"unknown_classification:{ticker}:{key[1]}")
                continue
            sentiment = str(item.get("sentiment") or "")
            confidence = float(item.get("confidence", -1))
            if sentiment not in VALID_SENTIMENTS:
                issues.append(f"invalid_sentiment:{ticker}:{key[1]}")
                continue
            if not 0 <= confidence <= 100:
                issues.append(f"invalid_confidence:{ticker}:{key[1]}")
                continue
            records.append(
                {
                    **article,
                    "sentiment": sentiment,
                    "confidence": confidence,
                    "reasoning": str(item.get("reasoning") or ""),
                }
            )
    missing = sorted(set(articles) - seen)
    issues.extend(f"missing_classification:{ticker}:{index}" for ticker, index in missing)
    return records, issues


def normalized_headline(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def dataset_audit(
    task_payload: dict[str, Any], records: list[dict[str, Any]], issues: list[str]
) -> dict[str, Any]:
    analysis_date = article_date(task_payload["analysis_date"])
    all_articles = task_articles(task_payload)
    links = [item["link"] for item in all_articles if item["link"]]
    link_counts = Counter(links)
    headline_counts = Counter(normalized_headline(item["headline"]) for item in all_articles)
    temporal_violations = [
        item for item in all_articles if item["date"] > analysis_date
    ]
    label_counts = Counter(item["sentiment"] for item in records)
    type_counts = Counter(item["content_type"] for item in all_articles)
    explicit_entity_mentions = sum(
        1
        for item in all_articles
        if item["company_name"].lower() in item["headline"].lower()
        or item["ticker"] in item["headline"]
    )
    return {
        "analysis_date": str(task_payload.get("analysis_date")),
        "task_count": len(task_payload.get("tasks", [])),
        "article_count": len(all_articles),
        "classification_count": len(records),
        "classification_coverage": round(len(records) / len(all_articles), 4)
        if all_articles
        else 0.0,
        "label_distribution": dict(sorted(label_counts.items())),
        "mean_confidence": round(
            sum(item["confidence"] for item in records) / len(records), 4
        )
        if records
        else None,
        "content_type_distribution": dict(sorted(type_counts.items())),
        "unique_links": len(link_counts),
        "duplicate_link_instances": sum(count - 1 for count in link_counts.values() if count > 1),
        "duplicate_headline_instances": sum(
            count - 1 for count in headline_counts.values() if count > 1
        ),
        "explicit_entity_mention_rate": round(
            explicit_entity_mentions / len(all_articles), 4
        )
        if all_articles
        else None,
        "temporal_violation_count": len(temporal_violations),
        "schema_issue_count": len(issues),
        "schema_issues": issues,
        "semantic_gold_labels_available": False,
        "semantic_accuracy": None,
    }


def collapse_events(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, pd.Timestamp], list[dict[str, Any]]] = defaultdict(list)
    for item in records:
        grouped[(item["ticker"], item["date"])].append(item)
    events = []
    for (ticker, date), items in sorted(grouped.items()):
        confidence_sum = sum(item["confidence"] for item in items)
        score = (
            sum(DIRECTION[item["sentiment"]] * item["confidence"] for item in items)
            / confidence_sum
            if confidence_sum
            else 0.0
        )
        sentiment = "positive" if score > 0.15 else "negative" if score < -0.15 else "neutral"
        events.append(
            {
                "ticker": ticker,
                "event_date": date,
                "sentiment": sentiment,
                "confidence": round(sum(item["confidence"] for item in items) / len(items), 4),
                "article_count": len(items),
                "content_types": sorted({item["content_type"] for item in items}),
            }
        )
    return events


def price_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    normalized = []
    for row in rows:
        date = row.get("date") or row.get("time")
        if not date or row.get("open") is None or row.get("close") is None:
            continue
        normalized.append(
            {
                "date": article_date(date),
                "open": float(row["open"]),
                "close": float(row["close"]),
            }
        )
    if not normalized:
        return pd.DataFrame(columns=["open", "close"])
    return (
        pd.DataFrame(normalized)
        .drop_duplicates("date", keep="last")
        .set_index("date")
        .sort_index()
    )


def fetch_price_frames(
    tickers: list[str], start_date: str, end_date: str, workers: int
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    frames: dict[str, pd.DataFrame] = {}
    failures: dict[str, str] = {}

    def fetch_one(ticker: str) -> tuple[str, pd.DataFrame]:
        return ticker, price_frame(get_prices(ticker, start_date, end_date))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_one, ticker): ticker for ticker in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                fetched_ticker, frame = future.result()
                if frame.empty:
                    failures[fetched_ticker] = "empty_price_history"
                else:
                    frames[fetched_ticker] = frame
            except Exception as exc:  # noqa: BLE001
                failures[ticker] = f"{type(exc).__name__}: {exc}"
    return frames, failures


def wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total <= 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [round(center - margin, 4), round(center + margin, 4)]


def evaluate_events(
    events: list[dict[str, Any]],
    price_frames: dict[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    horizons: list[int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    observations = []
    dropped = Counter()
    for event in events:
        frame = price_frames.get(event["ticker"])
        if frame is None or frame.empty:
            dropped["missing_stock_prices"] += 1
            continue
        future_dates = frame.index[frame.index > event["event_date"]]
        if future_dates.empty:
            dropped["no_next_trading_day"] += 1
            continue
        entry_date = future_dates[0]
        if entry_date not in benchmark.index:
            dropped["benchmark_missing_entry"] += 1
            continue
        entry_open = float(frame.loc[entry_date, "open"])
        benchmark_entry_open = float(benchmark.loc[entry_date, "open"])
        for horizon in horizons:
            target_position = horizon - 1
            if len(future_dates) <= target_position:
                dropped[f"insufficient_{horizon}d_history"] += 1
                continue
            exit_date = future_dates[target_position]
            if exit_date not in benchmark.index:
                dropped["benchmark_missing_exit"] += 1
                continue
            stock_return = float(frame.loc[exit_date, "close"]) / entry_open - 1
            benchmark_return = float(benchmark.loc[exit_date, "close"]) / benchmark_entry_open - 1
            abnormal_return = stock_return - benchmark_return
            label = event["sentiment"]
            band = HORIZON_NEUTRAL_BANDS[horizon]
            hit = (
                abnormal_return > 0
                if label == "positive"
                else abnormal_return < 0
                if label == "negative"
                else abs(abnormal_return) <= band
            )
            observations.append(
                {
                    "ticker": event["ticker"],
                    "event_date": event["event_date"].strftime("%Y-%m-%d"),
                    "entry_date": entry_date.strftime("%Y-%m-%d"),
                    "exit_date": exit_date.strftime("%Y-%m-%d"),
                    "horizon_trading_days": horizon,
                    "sentiment": label,
                    "confidence": event["confidence"],
                    "article_count": event["article_count"],
                    "stock_return": round(stock_return, 8),
                    "benchmark_return": round(benchmark_return, 8),
                    "abnormal_return": round(abnormal_return, 8),
                    "hit": bool(hit),
                }
            )
    return observations, dict(sorted(dropped.items()))


def event_metrics(observations: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in horizons:
        rows = [row for row in observations if row["horizon_trading_days"] == horizon]
        directional = [row for row in rows if row["sentiment"] != "neutral"]
        per_label = {}
        for label in sorted(VALID_SENTIMENTS):
            label_rows = [row for row in rows if row["sentiment"] == label]
            successes = sum(row["hit"] for row in label_rows)
            per_label[label] = {
                "count": len(label_rows),
                "hit_rate": round(successes / len(label_rows), 4) if label_rows else None,
                "mean_abnormal_return": round(
                    sum(row["abnormal_return"] for row in label_rows) / len(label_rows), 6
                )
                if label_rows
                else None,
            }
        all_successes = sum(row["hit"] for row in rows)
        directional_successes = sum(row["hit"] for row in directional)
        all_neutral_successes = sum(
            abs(row["abnormal_return"]) <= HORIZON_NEUTRAL_BANDS[horizon]
            for row in rows
        )
        all_neutral_hit_rate = (
            all_neutral_successes / len(rows) if rows else None
        )
        positive_mean = per_label["positive"]["mean_abnormal_return"]
        negative_mean = per_label["negative"]["mean_abnormal_return"]
        result[str(horizon)] = {
            "event_count": len(rows),
            "label_distribution": dict(Counter(row["sentiment"] for row in rows)),
            "all_label_hit_rate": round(all_successes / len(rows), 4) if rows else None,
            "all_label_hit_rate_wilson_95": wilson_interval(all_successes, len(rows)),
            "all_neutral_baseline_hit_rate": round(all_neutral_hit_rate, 4)
            if all_neutral_hit_rate is not None
            else None,
            "llm_minus_all_neutral_hit_rate": round(
                all_successes / len(rows) - all_neutral_hit_rate, 4
            )
            if rows and all_neutral_hit_rate is not None
            else None,
            "directional_event_count": len(directional),
            "directional_hit_rate": round(
                directional_successes / len(directional), 4
            )
            if directional
            else None,
            "directional_hit_rate_wilson_95": wilson_interval(
                directional_successes, len(directional)
            ),
            "neutral_band": HORIZON_NEUTRAL_BANDS[horizon],
            "per_label": per_label,
            "positive_minus_negative_mean_abnormal_return": round(
                positive_mean - negative_mean, 6
            )
            if positive_mean is not None and negative_mean is not None
            else None,
        }
    return result


def render_markdown(payload: dict[str, Any]) -> str:
    current = payload["current_dataset_audit"]
    historical = payload["historical_event_study"]
    lines = [
        "# KRX 뉴스 센티먼트 검증",
        "",
        f"- 결론: `accuracy_validated = {str(payload['validation_decision']['accuracy_validated']).lower()}`",
        f"- 현재 표본: {current['article_count']}건, 분류 coverage {current['classification_coverage']:.1%}",
        f"- 현재 시점 위반: {current['temporal_violation_count']}건",
        f"- 과거 표본: {historical['article_count']}건, 이벤트 {historical['collapsed_event_count']}건",
        f"- 과거 뉴스 비중: {historical['news_share']:.1%} (나머지는 DART 공시 제목)",
        "",
        "## 이후 초과수익 방향 적중률",
        "",
        "| 보유기간 | 전체 표본 | 비중립 표본 | LLM 전체 적중률 | 전부 중립 기준 | 차이 | 방향 적중률 | 방향 적중률 95% CI |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for horizon, metric in payload["predictive_metrics"].items():
        ci = metric["directional_hit_rate_wilson_95"]
        ci_text = "-" if ci is None else f"{ci[0]:.1%}~{ci[1]:.1%}"
        all_hit = metric["all_label_hit_rate"]
        directional_hit = metric["directional_hit_rate"]
        lines.append(
            f"| {horizon}일 | {metric['event_count']} | {metric['directional_event_count']} | "
            f"{all_hit:.1%} | {metric['all_neutral_baseline_hit_rate']:.1%} | "
            f"{metric['llm_minus_all_neutral_hit_rate']:+.1%}p | "
            f"{directional_hit:.1%} | {ci_text} |"
        )
    lines.extend(["", "## 판정 사유", ""])
    lines.extend(f"- {reason}" for reason in payload["validation_decision"]["reasons"])
    lines.extend(
        [
            "",
            "## 해석 제한",
            "",
            "- 사람 또는 독립 라벨러의 정답 라벨이 없어 의미 분류 정확도와 F1은 계산하지 않았다.",
            "- 과거 표본은 저장된 2026-04-28 후보를 사용했지만 현재 시점에 복원한 공시 목록이며 독립 홀드아웃이 아니다.",
            "- 공시 접수 시각이 없어 모든 이벤트를 다음 실제 거래일 시가에 체결한 것으로 보수 처리했다.",
            "- 중립 적중은 초과수익 절댓값이 1일 1%, 5일 2.5%, 20일 5% 이내인 경우다.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit and event-test KRX news sentiment labels")
    parser.add_argument("--current-tasks", required=True)
    parser.add_argument("--current-classifications", required=True)
    parser.add_argument("--historical-tasks", required=True)
    parser.add_argument("--historical-annotations", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--benchmark", default="^KS11")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    current_tasks = load_json(args.current_tasks)
    current_classifications = load_json(args.current_classifications)
    historical_tasks = load_json(args.historical_tasks)
    historical_annotations = load_json(args.historical_annotations)

    current_records, current_issues = classification_records(
        current_tasks, current_classifications
    )
    current_audit = dataset_audit(current_tasks, current_records, current_issues)
    historical_records = expand_annotations(historical_tasks, historical_annotations)
    historical_audit = dataset_audit(historical_tasks, historical_records, [])
    events = collapse_events(historical_records)

    start_date = min(event["event_date"] for event in events) - timedelta(days=7)
    tickers = sorted({event["ticker"] for event in events})
    frames, failures = fetch_price_frames(
        tickers,
        start_date.strftime("%Y-%m-%d"),
        args.end_date,
        args.workers,
    )
    benchmark = price_frame(
        get_prices(
            args.benchmark,
            start_date.strftime("%Y-%m-%d"),
            args.end_date,
        )
    )
    if benchmark.empty:
        raise ValueError("Benchmark price history is empty")
    horizons = sorted(HORIZON_NEUTRAL_BANDS)
    observations, dropped = evaluate_events(events, frames, benchmark, horizons)
    metrics = event_metrics(observations, horizons)

    historical_news_count = historical_audit["content_type_distribution"].get("news", 0)
    historical_summary = {
        **historical_audit,
        "annotation_source": historical_annotations.get("source"),
        "annotation_completed_before_return_lookup": bool(
            historical_annotations.get("annotation_completed_before_return_lookup")
        ),
        "collapsed_event_count": len(events),
        "news_share": round(
            historical_news_count / historical_audit["article_count"], 4
        ),
        "price_ticker_count": len(frames),
        "price_fetch_failures": failures,
        "dropped_event_horizons": dropped,
    }

    directional_counts = [
        metrics[str(horizon)]["directional_event_count"] for horizon in horizons
    ]
    decision_reasons = []
    if not current_audit["semantic_gold_labels_available"]:
        decision_reasons.append("독립적인 사람 정답 라벨이 없어 의미 분류 accuracy·macro-F1을 계산할 수 없음")
    if historical_summary["news_share"] < 0.5:
        decision_reasons.append("과거 표본의 대부분이 DART 공시 제목이라 현재 일반 뉴스 표본과 분포가 다름")
    if min(directional_counts, default=0) < 50:
        decision_reasons.append("긍정·부정 방향 표본이 50건 미만이라 방향 적중률 신뢰구간이 넓음")
    decision_reasons.append("검증 기간과 규칙이 결과 확인 전에 동결된 독립 홀드아웃이 아님")

    payload = {
        "schema_version": 1,
        "generated_at_data_through": args.end_date,
        "methodology": {
            "semantic_label_evaluation": "requires independent human gold labels; unavailable",
            "predictive_event_timing": "article date signal; next actual trading-day open entry",
            "benchmark": args.benchmark,
            "event_deduplication": "confidence-weighted ticker-date collapse",
            "horizons_trading_days": horizons,
            "neutral_abnormal_return_bands": {
                str(key): value for key, value in HORIZON_NEUTRAL_BANDS.items()
            },
        },
        "current_dataset_audit": current_audit,
        "historical_event_study": historical_summary,
        "predictive_metrics": metrics,
        "event_observations": observations,
        "validation_decision": {
            "accuracy_validated": False,
            "evidence_grade": "weak",
            "reasons": decision_reasons,
            "required_next_step": "independent stratified human gold set and frozen future holdout",
        },
    }
    Path(args.output).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(args.report).write_text(render_markdown(payload), encoding="utf-8")
    print(
        f"validation saved: {args.output} | events={len(events)} | "
        f"price_tickers={len(frames)} | accuracy_validated=false"
    )


if __name__ == "__main__":
    main()
