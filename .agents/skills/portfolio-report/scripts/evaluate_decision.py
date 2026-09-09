"""Prospective, initial-weight buy-and-hold evaluation from auditable local prices."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime
from pathlib import Path

from portfolio_decision import canonical_bytes, digest, load_snapshot, nonempty, number, safe_payload, timestamp


def _calendar(data, cutoff, end):
    calendar = data["calendar"]
    nonempty(calendar["id"], "calendar.id")
    nonempty(calendar["provider"], "calendar.provider")
    nonempty(calendar["reference"], "calendar.reference")
    if timestamp(calendar["coverage_start"]) > cutoff or timestamp(calendar["coverage_end"]) < end:
        raise ValueError("calendar coverage must span formation and evaluation")
    sessions = []
    previous_close = None
    for session in calendar["sessions"]:
        opening, close = timestamp(session["open_at"]), timestamp(session["close_at"])
        if opening >= close or (previous_close is not None and opening <= previous_close):
            raise ValueError("calendar sessions must be ordered, unique and nonoverlapping")
        previous_close = close
        if opening > cutoff and close <= end:
            sessions.append({"date": nonempty(session["date"], "session date"), "open": opening, "close": close})
    dates = [s["date"] for s in sessions]
    if len(dates) != len(set(dates)):
        raise ValueError("duplicate calendar session date")
    return sessions


def _observations(series, sessions, asof, label, fx=False):
    if series is None:
        return None, f"{label}: unavailable"
    for field in ("provider", "reference", "currency"):
        nonempty(series[field], f"{label}.{field}")
    if timestamp(series["retrieved_at"]) > asof:
        raise ValueError(f"{label}: data retrieved after evaluation")
    if not fx and series["price_basis"] != "total_return_adjusted":
        raise ValueError("only total_return_adjusted OHLC supported; dividends already reinvested")
    bars = {}
    for bar in series["bars"]:
        day = datetime.strptime(bar["date"], "%Y-%m-%d").date().isoformat()
        if day in bars:
            raise ValueError(f"{label}: duplicate bar {day}")
        bars[day] = bar
    result = []
    for session in sessions:
        bar = bars.get(session["date"])
        if bar is None or bar.get("status", "ok") != "ok":
            return None, f"{label}/{session['date']}: {bar.get('status') if bar else 'missing'}"
        try:
            result.append({"open": number(bar["open"], f"{label}.open", low=1e-12),
                           "close": number(bar["close"], f"{label}.close", low=1e-12)})
        except (KeyError, ValueError):
            return None, f"{label}/{session['date']}: invalid price"
    return result, None


def evaluate(result, data, as_of):
    safe_payload(data)
    canonical_bytes(data)
    asof = timestamp(as_of)
    doc = result["decision"]
    base = {"schema_version": "decision_evaluation_v1", "decision_id": result["decision_id"],
            "as_of": as_of, "decision_sha256": digest(result), "data_sha256": digest(data),
            "method": "initial_weights_buy_and_hold", "issues": [], "thesis_reviews": {},
            "performance_evidence": "observed period only; not calibrated future alpha"}
    if result["status"] not in {"ready", "conditional"}:
        return {**base, "status": "incomplete", "issues": ["decision has no valid final allocation"]}
    if asof < timestamp(doc["evaluation"]["review_at"]):
        return {**base, "status": "not_due", "review_at": doc["evaluation"]["review_at"]}
    if data["schema_version"] != "decision_prices_v1":
        raise ValueError("unsupported evaluation price schema")
    observed = timestamp(data["as_of"])
    end = timestamp(doc["evaluation"]["review_at"])
    if observed > asof:
        raise ValueError("data as_of after evaluation")
    if observed < end:
        return {**base, "status": "incomplete", "issues": ["evaluation data not yet covers review time"]}
    cutoff = max(timestamp(doc["created_at"]), timestamp(doc["input_cutoff"]))
    sessions = _calendar(data, cutoff, end)
    if not sessions:
        return {**base, "status": "incomplete", "issues": ["no completed investable sessions"]}
    assets = {a["ticker"]: a for a in doc["assets"]}
    selected = list(dict.fromkeys([*result["weights"], doc["benchmark"]]))
    calendar_id = data["calendar"]["id"]
    if any(assets[t]["calendar"] != calendar_id for t in selected):
        return {**base, "status": "incomplete", "issues": ["mixed calendars unsupported"]}
    prices, fx_rates, issues = {}, {}, []
    currencies = {assets[t]["quote"]["currency"] for t in selected}
    if result["cash_weight"] > 0:
        currencies.add(doc["cash"]["currency"])
    for currency in currencies:
        if currency == doc["base_currency"]:
            fx_rates[currency] = [{"open": 1., "close": 1.} for _ in sessions]
            continue
        fx = data.get("fx", {}).get(currency)
        if fx is not None and (fx.get("currency") != currency or fx.get("base_currency") != doc["base_currency"]):
            raise ValueError("FX currency pair mismatch; rates must be base units per foreign unit")
        values, issue = _observations(fx, sessions, asof, f"FX:{currency}", fx=True)
        if issue:
            issues.append(issue)
        else:
            fx_rates[currency] = values
    for ticker in selected:
        series = data.get("series", {}).get(ticker)
        if series is not None and (series.get("calendar") != calendar_id or series.get("currency") != assets[ticker]["quote"]["currency"]):
            raise ValueError(f"{ticker}: calendar/currency mismatch")
        values, issue = _observations(series, sessions, asof, ticker)
        if issue:
            issues.append(issue)
        else:
            prices[ticker] = values
    if issues:
        return {**base, "status": "incomplete", "issues": issues, "start_session": sessions[0]["date"], "end_session": sessions[-1]["date"]}
    rules = doc["evaluation"]

    def cost(currency, exit=False):
        return (rules["exit_cost_bps" if exit else "entry_cost_bps"] +
                (rules["fx_cost_bps"] if currency != doc["base_currency"] else 0)) / 10000

    def asset_curve(ticker, weight):
        currency = assets[ticker]["quote"]["currency"]
        bars, fx = prices[ticker], fx_rates[currency]
        initial = bars[0]["open"] * fx[0]["open"]
        values = [weight * bar["close"] * rates["close"] / initial / (1 + cost(currency)) for bar, rates in zip(bars, fx)]
        values[-1] *= 1 - cost(currency, exit=True)
        return values

    curves = {ticker: asset_curve(ticker, weight) for ticker, weight in result["weights"].items()}
    cash_currency = doc["cash"]["currency"]
    cash_fx = fx_rates[cash_currency] if result["cash_weight"] > 0 else [{"open": 1., "close": 1.} for _ in sessions]
    cash_fx_cost = rules["fx_cost_bps"] / 10000 if cash_currency != doc["base_currency"] else 0
    cash_curve = [result["cash_weight"] * (1 + doc["cash"]["annual_rate"]) ** ((s["close"] - sessions[0]["open"]).total_seconds() / (365.25 * 86400))
                  * f["close"] / cash_fx[0]["open"] / (1 + cash_fx_cost) for s, f in zip(sessions, cash_fx)]
    cash_curve[-1] *= 1 - cash_fx_cost
    nav = [cash_curve[i] + sum(values[i] for values in curves.values()) for i in range(len(sessions))]
    benchmark = asset_curve(doc["benchmark"], 1)
    daily = [nav[0] - 1] + [nav[i] / nav[i-1] - 1 for i in range(1, len(nav)) if nav[i-1] > 0]
    peak, drawdown = 1., 0.
    for value in nav:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    contributions = {t: values[-1] - result["weights"][t] for t, values in curves.items()}
    contributions["CASH"] = cash_curve[-1] - result["cash_weight"]
    reviews = data.get("thesis_reviews", {})
    for ticker in result["weights"]:
        review = reviews.get(ticker)
        if review is None:
            base["thesis_reviews"][ticker] = {"status": "not_reviewed"}
        else:
            if review["status"] not in {"intact", "contradicted", "uncertain"}:
                raise ValueError("invalid thesis review status")
            nonempty(review["reasoning"], "thesis review reasoning")
            if timestamp(review["as_of"]) > asof:
                raise ValueError("future thesis review")
            if not review["sources"]:
                raise ValueError("thesis review requires sources")
            base["thesis_reviews"][ticker] = review
    return {**base, "status": "complete", "start_session": sessions[0]["date"], "end_session": sessions[-1]["date"],
            "entry_at": sessions[0]["open"].isoformat(), "exit_at": sessions[-1]["close"].isoformat(),
            "base_currency": doc["base_currency"], "conventions": rules,
            "portfolio_return": nav[-1] - 1, "benchmark_return": benchmark[-1] - 1,
            "relative_return": nav[-1] - benchmark[-1], "contributions": contributions,
            "max_drawdown": drawdown, "annualized_volatility": statistics.stdev(daily) * math.sqrt(252) if len(daily) > 1 else None,
            "observations": len(sessions), "short_sample": len(sessions) < 60,
            "nav": [{"date": s["date"], "portfolio": p, "benchmark": b} for s, p, b in zip(sessions, nav, benchmark)],
            "price_provenance": {t: {k: v for k, v in data['series'][t].items() if k != 'bars'} for t in selected}}


def save_evaluation(folder, evaluation, reason):
    result = load_snapshot(folder)
    if evaluation["decision_id"] != result["decision_id"] or evaluation["decision_sha256"] != digest(result):
        raise ValueError("evaluation references a different decision")
    nonempty(reason, "evaluation/revision reason")
    safe_payload(evaluation)
    output = Path(folder) / "evaluations"
    output.mkdir(exist_ok=True)
    for version in range(1, 1000000):
        path = output / f"{version:06d}.json"
        if path.exists():
            continue
        payload = {**evaluation, "version": version, "reason": reason}
        body = canonical_bytes(payload)
        try:
            with path.open("xb") as handle:
                handle.write(body)
            return path
        except FileExistsError:
            continue
    raise ValueError("evaluation version limit reached")


def main():
    parser = argparse.ArgumentParser(description="고정된 추천의 구성 후 총수익과 가설 평가")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--prices-json", required=True)
    parser.add_argument("--as-of", required=True, help="timezone 포함 평가 시각")
    parser.add_argument("--reason", required=True, help="최초 평가 또는 자료 수정 이유")
    args = parser.parse_args()
    try:
        result = load_snapshot(args.snapshot)
        data = json.loads(Path(args.prices_json).read_text(encoding="utf-8"))
        evaluation = evaluate(result, data, args.as_of)
        path = save_evaluation(args.snapshot, evaluation, args.reason)
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": evaluation["status"], "output": str(path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
