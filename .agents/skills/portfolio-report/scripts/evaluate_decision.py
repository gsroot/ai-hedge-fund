"""Prospective, initial-weight buy-and-hold evaluation from auditable local prices."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from portfolio_decision import canonical_bytes, digest, load_snapshot, nonempty, number, safe_payload, timestamp


def _calendar(data, cutoff, end):
    calendar = data["calendar"]
    nonempty(calendar["id"], "calendar.id")
    nonempty(calendar["provider"], "calendar.provider")
    nonempty(calendar["reference"], "calendar.reference")
    known_zones = {"XNYS": "America/New_York", "XNAS": "America/New_York", "XKRX": "Asia/Seoul"}
    zone_name = calendar.get("timezone", known_zones.get(calendar["id"]))
    if calendar["id"] in known_zones and zone_name != known_zones[calendar["id"]]:
        raise ValueError("calendar timezone disagrees with exchange")
    try:
        zone = ZoneInfo(zone_name) if zone_name else None
    except (TypeError, ZoneInfoNotFoundError) as exc:
        raise ValueError("invalid calendar timezone") from exc
    if timestamp(calendar["coverage_start"]) > cutoff or timestamp(calendar["coverage_end"]) < end:
        raise ValueError("calendar coverage must span formation and evaluation")
    sessions = []
    previous_close = None
    previous_day = None
    for session in calendar["sessions"]:
        opening, close = timestamp(session["open_at"]), timestamp(session["close_at"])
        day = datetime.strptime(session["date"], "%Y-%m-%d").date()
        local_open = opening.astimezone(zone) if zone else datetime.fromisoformat(session["open_at"].replace("Z", "+00:00"))
        local_close = close.astimezone(zone) if zone else datetime.fromisoformat(session["close_at"].replace("Z", "+00:00"))
        if day != local_open.date() or day != local_close.date() or (previous_day is not None and day <= previous_day):
            raise ValueError("session date must match ordered local exchange opens and closes")
        previous_day = day
        if opening >= close or (previous_close is not None and opening <= previous_close):
            raise ValueError("calendar sessions must be ordered, unique and nonoverlapping")
        previous_close = close
        if opening > cutoff and close <= end:
            sessions.append({"date": day.isoformat(), "open": opening, "close": close})
    return sessions


def _observations(series, sessions, asof, label, fx=False):
    if series is None:
        return None, f"{label}: unavailable"
    for field in ("provider", "reference", "currency"):
        nonempty(series[field], f"{label}.{field}")
    retrieved = timestamp(series["retrieved_at"])
    if retrieved > asof:
        raise ValueError(f"{label}: data retrieved after evaluation")
    if retrieved < sessions[-1]["close"]:
        return None, f"{label}: retrieved before final session close"
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


def _unit_growth(ticker, assets, doc, data, sessions, asof, exchange):
    is_cash = ticker is None
    asset = doc["cash"] if is_cash else assets[ticker]
    if not is_cash and asset["calendar"] != data["calendar"]["id"]:
        return None, None, "mixed calendars unsupported"
    base_currency = doc["base_currency"]
    currency = asset["currency"] if is_cash else asset["quote"]["currency"]
    if currency not in exchange:
        fx = data.get("fx", {}).get(currency)
        if fx is not None and (fx.get("currency"), fx.get("base_currency")) != (currency, base_currency):
            raise ValueError("FX currency pair mismatch; rates must be base units per foreign unit")
        exchange[currency] = _observations(fx, sessions, asof, f"FX:{currency}", fx=True)
    rates, issue = exchange[currency]
    if issue:
        return None, None, issue
    if is_cash:
        years = [(s["close"] - sessions[0]["open"]).total_seconds() / (365.25 * 86400) for s in sessions]
        local_growth = [(1 + asset["annual_rate"]) ** elapsed for elapsed in years]
    else:
        series = data.get("series", {}).get(ticker)
        if series is not None and (series.get("calendar"), series.get("currency")) != (asset["calendar"], currency):
            raise ValueError(f"{ticker}: calendar/currency mismatch")
        bars, issue = _observations(series, sessions, asof, ticker)
        if issue:
            return None, None, issue
        local_growth = [bar["close"] / bars[0]["open"] for bar in bars]
    rules = doc["evaluation"]
    gross = [value * fx["close"] / rates[0]["open"] for value, fx in zip(local_growth, rates)]
    fx_bps = rules["fx_cost_bps"] if currency != base_currency else 0
    entry = (fx_bps + (0 if is_cash else rules["entry_cost_bps"])) / 10000
    exit_cost = (fx_bps + (0 if is_cash else rules["exit_cost_bps"])) / 10000
    fresh = [value / (1 + entry) for value in gross]
    fresh[-1] *= 1 - exit_cost
    return fresh, gross[-1], None


def _unit_paths(tickers, doc, data, sessions, asof, *, isolate_errors):
    """Price each instrument once. Alternative-only failures stay attributable."""
    assets = {asset["ticker"]: asset for asset in doc["assets"]}
    exchange = {doc["base_currency"]: ([{"open": 1.0, "close": 1.0} for _ in sessions], None)}
    fresh, terminal_gross, issues = {}, {}, {}
    for ticker in sorted(tickers, key=lambda item: (item is not None, item or "")):
        try:
            curve, gross, issue = _unit_growth(ticker, assets, doc, data, sessions, asof, exchange)
        except (KeyError, TypeError, ValueError) as exc:
            if not isolate_errors:
                raise
            issues[ticker] = f"{ticker}: invalid observation: {exc}"
            continue
        if issue:
            issues[ticker] = issue
        else:
            fresh[ticker], terminal_gross[ticker] = curve, gross
    return fresh, terminal_gross, issues


def _alternative_outcomes(plans, paths, gross, issues):
    outcomes = {}
    for name, plan in plans.items():
        row = {"formation_status": plan["status"]}
        outcomes[name] = row
        weights = plan["weights"]
        if weights is None or plan["status"] == "unavailable":
            row.update(status="unavailable", issues=plan.get("input_issues") or ["no usable frozen allocation"])
            continue
        positions = {None if t == "CASH" else t: w for t, w in weights.items() if w > 0}
        errors = sorted({issues[t] for t in positions if t in issues})
        if errors:
            row.update(status="incomplete", issues=errors)
            continue
        fresh_nav = sum(w * paths[t][-1] for t, w in positions.items())
        row.update(status="complete", fresh_capital_return=fresh_nav - 1, from_holdings_return=None)
        transition = plan["transition"]
        if transition["status"] == "estimated":
            cost = number(transition["estimated_cost_weight"], "transition cost fraction", low=0, high=1)
            row["from_holdings_return"] = (1 - cost) * sum(w * gross[t] for t, w in positions.items()) - 1
        else:
            row["transition_issue"] = transition.get("reason", "formation costs unknown")
    chosen = outcomes["selected"]
    for row in outcomes.values():
        if row["status"] == "complete":
            for field, diff in (("fresh_capital_return", "selected_minus_alternative_fresh"),
                                ("from_holdings_return", "selected_minus_alternative_from_holdings")):
                row[diff] = chosen[field] - row[field] if chosen.get(field) is not None and row[field] is not None else None
    return outcomes


def evaluate(result, data, as_of):
    if result.get("preview"):
        raise ValueError("only a frozen final decision can be evaluated")
    safe_payload(data)
    canonical_bytes(data)
    asof = timestamp(as_of)
    doc = result["decision"]
    schema = "decision_evaluation_v2" if "portfolio_comparison" in result else "decision_evaluation_v1"
    base = {"schema_version": schema, "decision_id": result["decision_id"],
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
    selected = {**result["weights"]}
    if result["cash_weight"]:
        selected[None] = result["cash_weight"]
    plans = result.get("portfolio_comparison", {}).get("portfolios", {})
    tickers = set(selected) | {doc["benchmark"]}
    for plan in plans.values():
        if plan["status"] != "unavailable":
            tickers.update(None if t == "CASH" else t for t, w in (plan["weights"] or {}).items() if w > 0)
    paths, gross, issues = _unit_paths(tickers, doc, data, sessions, observed, isolate_errors=bool(plans))
    base.update(start_session=sessions[0]["date"], end_session=sessions[-1]["date"])
    if plans:
        base["alternative_outcomes"] = _alternative_outcomes(plans, paths, gross, issues)
        base["comparison_price_sources"] = {
            t: {k: v for k, v in data["series"][t].items() if k != "bars"}
            for t in sorted(paths.keys() - {None})
        }
        base["alternative_methods"] = {
            "fresh_capital_return": "initial target weights; enter at first open; liquidate at last close",
            "from_holdings_return": "frozen estimated transition costs deducted pro rata at entry; mark to market at last close",
            "difference": "selected minus comparator, in the same base currency and cost convention",
        }
    required = set(selected) | {doc["benchmark"]}
    missing = sorted({issues[t] for t in required if t in issues})
    if missing:
        return {**base, "status": "incomplete", "issues": missing}
    nav = [sum(w * paths[t][i] for t, w in selected.items()) for i in range(len(sessions))]
    benchmark = paths[doc["benchmark"]]
    daily = [nav[0] - 1] + [nav[i] / nav[i-1] - 1 for i in range(1, len(nav)) if nav[i-1] > 0]
    peak, drawdown = 1., 0.
    for value in nav:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    contributions = {t: w * (paths[t][-1] - 1) for t, w in selected.items() if t is not None}
    contributions["CASH"] = selected[None] * (paths[None][-1] - 1) if None in selected else 0.0
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
            "base_currency": doc["base_currency"], "conventions": doc["evaluation"],
            "portfolio_return": nav[-1] - 1, "benchmark_return": benchmark[-1] - 1,
            "relative_return": nav[-1] - benchmark[-1], "contributions": contributions,
            "max_drawdown": drawdown, "annualized_volatility": statistics.stdev(daily) * math.sqrt(252) if len(daily) > 1 else None,
            "observations": len(sessions), "short_sample": len(sessions) < 60,
            "nav": [{"date": s["date"], "portfolio": p, "benchmark": b} for s, p, b in zip(sessions, nav, benchmark)],
            "price_provenance": {t: {k: v for k, v in data['series'][t].items() if k != 'bars'} for t in sorted(required - {None})}}


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
