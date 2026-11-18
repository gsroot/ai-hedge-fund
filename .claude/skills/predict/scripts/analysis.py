"""Collect date-scoped observations and rank companies within the requested universe."""
import statistics
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from config import FACTOR_WEIGHTS, INVESTOR_WEIGHTS, MAX_WORKERS
from data_fetcher import get_financial_metrics, get_prices, get_insider_trades, get_company_news, batch_fetch_prices
from factor_scoring import (
    get_market_cap_category, calculate_value_score, calculate_growth_score, calculate_quality_score,
    calculate_momentum_score, calculate_enhanced_momentum_score, calculate_safety_score,
    calculate_sentiment_score, calculate_insider_activity_score,
)
from investor_scoring import (
    calculate_sector_stats, calculate_buffett_score, calculate_lynch_score, calculate_graham_score,
    calculate_fisher_score, calculate_druckenmiller_score, generate_investor_warnings,
)
from research_ranking import (
    FINANCIAL_INPUTS, MIN_PRICE_OBSERVATIONS, is_number, observed_financials, observed_prices, rank_research_rows,
)
from ticker_utils import completed_korean_price_date, is_korean_ticker


def ranking_sentiment_score(diagnostic_score, *, accuracy_validated=False):
    """Legacy factor API. Live keyword diagnostics have no relative rank effect."""
    return max(0.0, min(10.0, float(diagnostic_score))) if accuracy_validated else 5.0


def calculate_weighted_factor_score(factor_scores, factor_weights=None):
    """Historical raw factor blend for existing callers."""
    weights = FACTOR_WEIGHTS if factor_weights is None else factor_weights
    if set(weights) != set(FACTOR_WEIGHTS):
        raise ValueError("factor_weights keys must match config.FACTOR_WEIGHTS")
    if any(float(weight) < 0 for weight in weights.values()):
        raise ValueError("factor_weights cannot contain negative values")
    return sum(float(factor_scores[factor]) * float(weights[factor]) for factor in FACTOR_WEIGHTS)


@dataclass(frozen=True)
class BatchAnalysis:
    results: tuple[dict, ...]
    excluded: tuple[dict, ...]


def summarize_exclusions(excluded):
    return dict(sorted(Counter(item["reason"] for item in excluded).items()))


def _price_start(end_date):
    return (date.fromisoformat(end_date) - timedelta(days=120)).isoformat()


def _percent(value):
    return round(value * 100, 1) if is_number(value) else None


def _clean_snapshot(snapshot):
    text_fields = {"ticker", "company_name", "sector", "industry", "report_period", "provider", "quote_type", "pe_basis"}
    return {key: value for key, value in snapshot.items() if is_number(value) or
            (key in text_fields and isinstance(value, str))}


def _auxiliary(fetch, ticker, end_date, limit):
    try:
        rows = fetch(ticker, end_date, limit=limit) or []
    except Exception as exc:
        return [], f"unavailable:{type(exc).__name__}"
    return rows, "observed" if rows else "no_observations"


def _directional_trades(trades):
    """Only explicit purchase/sale evidence supports a directional insider factor."""
    directional = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        event = str(trade.get("transaction_type") or "").lower().strip()
        if re.search(r"gift|award|grant|option|exercis|conversion|withhold|tax|to cover", event):
            continue
        if re.match(r"^(?:open[ -]market\s+)?(?:purchase|buy|bought|p)\b|^장내매수", event):
            side = "buy"
        elif re.match(r"^(?:open[ -]market\s+)?(?:sale|sell|sold|s)\b|^장내매도", event):
            side = "sell"
        else:
            continue
        ownership = str(trade.get("ownership_type") or "").strip().lower()
        directional.append({**trade, "transaction_type": side,
                            "ownership_type": "direct" if ownership in {"d", "direct"} else ""})
    return directional


def _style_diagnostics(metrics, raw, momentum, details, sector_stats):
    """Compute a style only when its required blocks exist. Never used as rank inputs."""
    value, growth, quality, safety = (raw[key] for key in FINANCIAL_INPUTS)
    insider = raw["insider"]
    styles = {}
    if None not in (growth, quality, safety):
        styles["buffett"] = calculate_buffett_score(metrics, growth, quality, safety)
    if None not in (growth, insider, value):
        styles["lynch"] = calculate_lynch_score(metrics, growth, 5, insider, sector_stats)
    if value is not None and safety is not None:
        styles["graham"] = calculate_graham_score(metrics, sector_stats)
    if growth is not None and quality is not None:
        styles["fisher"] = calculate_fisher_score(metrics, growth, quality)
    if momentum is not None and growth is not None:
        styles["druckenmiller"] = calculate_druckenmiller_score(momentum, growth, details, metrics)
    total_weight = sum(INVESTOR_WEIGHTS[name] for name in styles)
    mean = sum(score * INVESTOR_WEIGHTS[name] for name, score in styles.items()) / total_weight if total_weight else None
    spread = statistics.stdev(styles.values()) if len(styles) >= 2 else None
    consensus = {
        "bullish": [name for name in styles if styles[name] >= 7],
        "bearish": [name for name in styles if styles[name] <= 3],
        "std": round(spread, 2) if spread is not None else None,
        "level": None if spread is None else ("high" if spread < 1.5 else "medium" if spread < 2.5 else "low"),
    }
    return styles, mean, consensus


def analyze_single_ticker(ticker, end_date, prefetched_prices=None, strategy="hybrid", skip_news=False,
                          sector_stats=None, factor_weights=None):
    row, _ = analyze_single_ticker_detailed(ticker, end_date, prefetched_prices, strategy, skip_news,
                                            sector_stats, factor_weights)
    return row


def analyze_single_ticker_detailed(ticker, end_date, prefetched_prices=None, strategy="hybrid", skip_news=False,
                                   sector_stats=None, factor_weights=None, *, prefetched_metrics=None, for_batch=False):
    """A standalone research score uses a one-company comparison universe."""
    try:
        if strategy not in {"fundamental", "hybrid", "momentum"}:
            raise ValueError("unknown strategy")
        metrics = []
        if strategy != "momentum":
            metrics = prefetched_metrics
            if metrics is None:
                metrics = get_financial_metrics(ticker, end_date, period="annual", limit=2)
            if not metrics:
                return None, "metrics_unavailable"
            if str(metrics[0].get("quote_type") or "").upper() in {"ETF", "MUTUALFUND", "INDEX", "FUTURE", "CURRENCY", "CRYPTOCURRENCY"}:
                return None, "non_company_instrument"
        bars = prefetched_prices if prefetched_prices is not None else get_prices(ticker, _price_start(end_date), end_date)
        latest_price_day = completed_korean_price_date(end_date) if is_korean_ticker(ticker) else end_date
        prices, reason = observed_prices(bars, end_date, latest_price_day=latest_price_day)
        if reason:
            return None, reason
        long_window = len(prices) >= MIN_PRICE_OBSERVATIONS
        if strategy == "momentum" and not long_window:
            return None, "insufficient_price_history"

        m = _clean_snapshot(metrics[0]) if metrics else {}
        metrics = [m] if m else []
        estimates = None
        if metrics and not is_korean_ticker(ticker) and end_date == datetime.now(UTC).date().isoformat():
            from financial_datasets_api import get_analyst_estimates
            try:
                estimates = get_analyst_estimates(ticker, end_date)
            except Exception:
                pass
        inputs = observed_financials(m, estimates)
        if strategy != "momentum" and sum(bool(values) for values in inputs.values()) < 2:
            return None, "insufficient_fundamental_coverage"
        raw = dict.fromkeys((*FINANCIAL_INPUTS, "insider", "momentum"))
        explanations = []
        for group, fn in (("value", calculate_value_score), ("growth", calculate_growth_score),
                          ("quality", calculate_quality_score), ("safety", calculate_safety_score)):
            if inputs[group]:
                if group in {"quality", "safety"}:
                    raw[group], notes = fn(metrics, observed=True)
                elif group == "growth":
                    raw[group], notes = fn(metrics, inputs["growth"])
                else:
                    raw[group], notes = fn(metrics)
                explanations.extend(notes)

        enhanced, momentum_details = calculate_enhanced_momentum_score(prices) if long_window else (None, {})
        classical, momentum_notes = calculate_momentum_score(prices) if long_window else (None, [])
        # Preserve the raw factor definition used by the common factor evidence artifacts.
        raw["momentum"] = classical if strategy != "momentum" else enhanced
        if strategy != "fundamental":
            explanations.extend(momentum_notes)
        news, trades = [], []
        news_status = insider_status = "not_requested"
        if strategy != "momentum" and not skip_news:
            news, news_status = _auxiliary(get_company_news, ticker, end_date, 20)
            trades, insider_status = _auxiliary(get_insider_trades, ticker, end_date, 50)
        directional = _directional_trades(trades)
        insider_score, insider_notes = calculate_insider_activity_score(directional)
        if directional:
            raw["insider"] = insider_score
            explanations.extend(insider_notes)
        elif trades:
            insider_status = "no_usable_observations"
        raw_sentiment, sentiment_notes = calculate_sentiment_score(news) if news else (None, [])
        styles, ensemble, consensus = _style_diagnostics(metrics, raw, enhanced, momentum_details, sector_stats)
        warnings = generate_investor_warnings(ticker, styles, metrics) if metrics else []
        cap = m.get("market_cap")
        category, display = get_market_cap_category(cap, currency="KRW" if is_korean_ticker(ticker) else None)
        row = {
            "ticker": ticker, "company_name": m.get("company_name") or ticker, "strategy": strategy,
            "data_as_of": end_date, "rank_inputs": raw, "factors": explanations[:5],
            "scores": {**raw, "sentiment": 5.0 if strategy != "momentum" else None, "enhanced_momentum": enhanced},
            "research_evidence": {
                "price_start": prices[0]["time"], "price_end": prices[-1]["time"], "last_close": prices[-1]["close"],
                "last_price_providers": prices[-1]["providers"],
                "price_observations": len(prices), "momentum_window_available": long_window,
                "fundamental_fields": inputs, "financial_snapshot_date": end_date if metrics else None,
                "financial_provider": m.get("provider"), "quote_type": m.get("quote_type"), "pe_basis": m.get("pe_basis"),
                "cash_flow_observations": {key: m[key] for key in ("operating_cashflow", "free_cash_flow")
                                          if is_number(m.get(key))},
                "missing_fundamental_groups": [key for key in inputs if not inputs[key]],
                "insider_status": insider_status, "keyword_news_status": news_status,
                "insider_events_received": len(trades), "insider_events_used": len(directional),
            },
            "sentiment_diagnostics": {
                "source": "keyword", "raw_score": raw_sentiment, "ranking_policy": "risk_and_explanation_only",
                "ranking_contribution_applied": False, "accuracy_validated": False, "factors": sentiment_notes,
            },
            "momentum_details": momentum_details, "ensemble_score": round(ensemble, 2) if ensemble is not None else None,
            "investor_scores": {key: round(value, 2) for key, value in styles.items()},
            "investor_consensus": consensus, "investor_warnings": warnings,
            "market_cap": {"value": cap, "display": display, "category": category},
            "metrics": {"pe": m.get("price_to_earnings_ratio"), "pb": m.get("price_to_book_ratio"),
                        "roe": _percent(m.get("return_on_equity")), "revenue_growth": _percent(m.get("revenue_growth")),
                        "peg": m.get("peg_ratio"), "sector": m.get("sector")},
        }
        if for_batch:
            return row, None
        ranked = rank_research_rows([row], strategy, factor_weights)
        return (ranked[0], None) if ranked else (None, "no_weighted_observations")
    except Exception as exc:
        return None, f"analysis_error:{type(exc).__name__}"


def run_batch_analysis(tickers, end_date, max_workers=MAX_WORKERS, strategy="hybrid", factor_weights=None, *, skip_news=False):
    return list(run_batch_analysis_with_exclusions(tickers, end_date, max_workers, strategy, factor_weights, skip_news=skip_news).results)


def run_batch_analysis_with_exclusions(tickers, end_date, max_workers=MAX_WORKERS, strategy="hybrid", factor_weights=None,
                                       *, skip_news=False):
    tickers = list(dict.fromkeys(tickers))
    all_prices = batch_fetch_prices(tickers, _price_start(end_date), end_date)
    rows, excluded, snapshots = [], [], {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        if strategy != "momentum":
            futures = {pool.submit(get_financial_metrics, t, end_date, period="annual", limit=2): t for t in tickers}
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    snapshots[ticker] = future.result() or []
                except Exception as exc:
                    excluded.append({"ticker": ticker, "reason": f"analysis_error:{type(exc).__name__}"})
        active = [ticker for ticker in tickers if strategy == "momentum" or ticker in snapshots]
        sectors = calculate_sector_stats([_clean_snapshot(m[0]) for m in snapshots.values() if m]) if snapshots else {}
        futures = {
            pool.submit(analyze_single_ticker_detailed, ticker, end_date, prefetched_prices=all_prices.get(ticker),
                        prefetched_metrics=snapshots.get(ticker), strategy=strategy, sector_stats=sectors,
                        factor_weights=factor_weights, skip_news=skip_news, for_batch=True): ticker for ticker in active
        }
        for future in as_completed(futures):
            row, reason = future.result()
            if row is None:
                excluded.append({"ticker": futures[future], "reason": reason})
            else:
                rows.append(row)
    ranked = rank_research_rows(rows, strategy, factor_weights)
    included = {row["ticker"] for row in ranked}
    excluded.extend({"ticker": row["ticker"], "reason": "no_weighted_observations"} for row in rows if row["ticker"] not in included)
    return BatchAnalysis(tuple(ranked), tuple(sorted(excluded, key=lambda row: row["ticker"])))
