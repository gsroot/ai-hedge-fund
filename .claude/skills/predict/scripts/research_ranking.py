"""Cross-sectional research ranking, evidence availability and candidate selection."""
from bisect import bisect_left, bisect_right
from datetime import date, datetime
from math import isfinite

from config import FACTOR_WEIGHTS

RANKING_POLICY_ID = "observed_peer_factors_v2"
OBSERVED_FACTOR_SPEC_ID = "predict_factor_observed_v2"
MIN_PRICE_OBSERVATIONS = 60   # Existing enhanced momentum scorer's long window.
MAX_PRICE_LAG_DAYS = 7       # Same calendar-day tolerance as the readiness sample.
RANK_LEADERS = 10

FINANCIAL_INPUTS = {
    "value": ("price_to_earnings_ratio", "price_to_book_ratio", "enterprise_value_to_ebitda", "free_cash_flow_yield"),
    "growth": ("revenue_growth", "earnings_per_share_growth", "peg_ratio", "forward_revenue_growth", "forward_eps_growth"),
    "quality": ("return_on_equity", "return_on_invested_capital", "operating_margin", "net_margin"),
    "safety": ("debt_to_equity", "current_ratio", "interest_coverage", "quick_ratio", "cash_ratio",
               "operating_cash_flow_ratio", "dividend_yield", "held_percent_insiders", "held_percent_institutions"),
}


def is_number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and isfinite(value)


def observed_financials(metrics, estimates):
    source = {**metrics, **(estimates or {})}
    return {
        group: {key: source[key] for key in fields if is_number(source.get(key))}
        for group, fields in FINANCIAL_INPUTS.items()
    }


def observed_prices(prices, end_date, *, latest_price_day=None):
    """Use only dated, finite, positive closes within the fetch window."""
    cutoff = date.fromisoformat(end_date)
    last_eligible = date.fromisoformat(latest_price_day) if latest_price_day else cutoff
    close_by_day = {}
    providers = {}
    for bar in prices or ():
        if not isinstance(bar, dict):
            continue
        try:
            stamp = bar.get("time") or bar.get("date")
            day = datetime.fromisoformat(stamp).date()
        except (TypeError, ValueError, KeyError):
            continue
        close = bar.get("close")
        if day > last_eligible or not (0 <= (cutoff - day).days <= 120 and is_number(close) and close > 0):
            continue
        if day in close_by_day and close_by_day[day] != close:
            return [], "conflicting_daily_closes"
        close_by_day[day] = close
        if isinstance(bar.get("provider"), str):
            providers.setdefault(day, set()).add(bar["provider"])
    if not close_by_day:
        return [], "prices_unavailable"
    if (cutoff - max(close_by_day)).days > MAX_PRICE_LAG_DAYS:
        return [], "prices_stale"
    return [{"time": day.isoformat(), "close": close_by_day[day], "providers": sorted(providers.get(day, set()))}
            for day in sorted(close_by_day)], None


def score_compatibility_fields(score):
    """Historical JSON fields used by stored-input report and replay clients."""
    if score >= 8:
        signal = "strong_buy"
    elif score >= 5:
        signal = "buy"
    elif score >= 2:
        signal = "hold"
    elif score >= 0:
        signal = "weak_sell"
    else:
        signal = "sell"
    mapping = max(-0.30, min(0.40, (score - 3) / 10 * 0.35))
    return {"signal": signal, "score_implied_return_pct": round(mapping * 100, 1),
            "return_estimate": {"calibrated": False, "method": "heuristic_score_mapping",
                                "label": "점수 환산값(예상수익률 아님)"}}


def _cohort_percentiles(rows, factors):
    distributions = {}
    for factor in factors:
        distributions[factor] = sorted(
            row["rank_inputs"][factor] for row in rows
            if is_number(row["rank_inputs"].get(factor))
        )
    return distributions


def _rank_row(row, strategy, weights, distributions):
    percentiles = {}
    for factor, distribution in distributions.items():
        value = row["rank_inputs"].get(factor)
        if is_number(value):
            # Mid-distribution percentile: ties and a lone observation occupy their midpoint.
            percentiles[factor] = 5 * (bisect_left(distribution, value) + bisect_right(distribution, value)) / len(distribution)
    applicable = {key: weights[key] for key in percentiles if weights[key] > 0}
    if strategy == "momentum":
        total = row["scores"]["enhanced_momentum"]
        applied = {"momentum": 1.0}
        fundamental = None
    else:
        if not applicable:
            return None
        budget = sum(weights[key] for key in distributions) + weights["sentiment"]
        news_reserve = weights["sentiment"] / budget
        applied = {key: weight / budget for key, weight in applicable.items()}
        if news_reserve:
            applied["sentiment"] = news_reserve
        total = 5 + sum((percentiles[key] - 5) * applied[key] for key in applicable)
        fund = {key: weight for key, weight in applicable.items() if key != "momentum"}
        fundamental = sum(percentiles[key] * weight for key, weight in fund.items()) / sum(fund.values()) if fund else None
    total = round(total, 4)
    return {**row, "total_score": total, **score_compatibility_fields(total),
            "scores": {**row["scores"], "fundamental": round(fundamental, 4) if fundamental is not None else None},
            "factor_percentiles": {k: round(v, 4) for k, v in percentiles.items()},
            "factor_peer_counts": {k: len(distributions[k]) for k in percentiles},
            "research_weights": applied,
            "observed_weight_share": sum(weight for key, weight in applied.items() if key != "sentiment")}


def rank_research_rows(rows, strategy, weights=None):
    """Rank in the requested cohort. A single-stock call has no cross-sectional comparison."""
    factors = list(FINANCIAL_INPUTS) + ["insider"]
    if strategy in {"hybrid", "momentum"}:
        factors.append("momentum")
    if strategy == "momentum":
        factors = ["momentum"]
    distributions = _cohort_percentiles(rows, factors)
    ranked = []
    for row in rows:
        result = _rank_row(row, strategy, FACTOR_WEIGHTS if weights is None else weights, distributions)
        if result is not None:
            ranked.append(result)
    ranked.sort(key=lambda row: (-row["total_score"], row["ticker"]))
    return [{**row, "rank": index} for index, row in enumerate(ranked, 1)]


def build_research_shortlist(rankings):
    """Top-ranked stocks plus the best observed company per sector and effective factor."""
    reasons = {}
    sectors = set()
    leaders = {}
    for row in rankings:
        ticker = row["ticker"]
        if row["rank"] <= RANK_LEADERS:
            reasons.setdefault(ticker, []).append("rank")
        sector = (row.get("metrics") or {}).get("sector")
        if sector and sector.lower() not in {"unknown", "n/a", "_unknown"} and sector not in sectors:
            reasons.setdefault(ticker, []).append(f"sector:{sector}")
            sectors.add(sector)
        for factor, value in row.get("factor_percentiles", {}).items():
            if factor not in row.get("research_weights", {factor: 1}):
                continue
            # Require a positive cross-sectional distinction for a factor challenger.
            if value > 5 and (factor not in leaders or value > leaders[factor][0]):
                leaders[factor] = (value, ticker)
    for factor, (_, ticker) in sorted(leaders.items()):
        reasons.setdefault(ticker, []).append(f"factor:{factor}")
    return {
        "policy_id": "research_shortlist_v1", "rank_leaders": RANK_LEADERS,
        "universe_ranked": len(rankings),
        "candidates": [{"ticker": row["ticker"], "rank": row["rank"], "reasons": reasons[row["ticker"]]}
                       for row in rankings if row["ticker"] in reasons],
    }
