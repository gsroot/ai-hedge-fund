"""Historical downside of proposed allocations from observed closes in the decision currency."""
from __future__ import annotations

import math
from datetime import date

import pandas as pd


def _unavailable(reason):
    return {"status": "unavailable", "reason": reason}


def _series(history, label, start, end):
    closes = history.get("relative_closes") if isinstance(history, dict) else None
    if not isinstance(closes, dict) or not closes:
        raise ValueError(f"missing_{label}")
    items = {}
    for day, price in closes.items():
        stamp = pd.Timestamp(date.fromisoformat(day))
        if not start <= stamp <= end:
            raise ValueError(f"outside_lookback:{label}")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            raise ValueError(f"invalid_close:{label}")
        if stamp in items:
            raise ValueError(f"duplicate_date:{label}")
        items[stamp] = price
    return pd.Series(items, dtype=float).sort_index()


def _components(snapshot, weights, currencies, base, cash_currency, start, end):
    if any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or w < 0 for w in weights.values()):
        raise ValueError("invalid_weight")
    if sum(weights.values()) > 1 + 1e-8:
        raise ValueError("invalid_total_weight")

    def fx(currency):
        if not currency:
            raise ValueError("missing_currency")
        if currency == base:
            return 1.0
        pair = f"{currency}/{base}"
        history = snapshot.get("fx_history", {}).get(pair)
        if not history or history.get("direction") != "base_per_foreign" or history.get("status") != "available":
            raise ValueError(f"missing_fx:{pair}")
        return _series(history, f"fx:{pair}", start, end)

    legs = []
    for ticker, weight in weights.items():
        if weight == 0:
            continue
        history = snapshot["price_history"].get(ticker)
        close = _series(history, f"price:{ticker}", start, end)
        legs.append((weight, (close * fx(currencies.get(ticker))).dropna()))
    cash = max(0.0, 1.0 - sum(weights.values()))
    if cash > 1e-8 and cash_currency != base:
        legs.append((cash, fx(cash_currency)))
        cash = 0.0
    return cash, legs


def _common_dates(legs):
    dates = None
    for _, series in legs:
        dates = series.index if dates is None else dates.intersection(series.index)
    return dates


def _coverage(dates, end, minimum, max_age, max_gap):
    if dates is None or len(dates) == 0:
        return {**_unavailable("insufficient_common_observations"), "observations": 0}
    info = {"observations": len(dates) - 1, "first_date": str(dates[0].date()), "last_date": str(dates[-1].date())}
    if len(dates) <= minimum:
        return {**info, **_unavailable("insufficient_common_observations")}
    if (end - dates[-1]).days > max_age:
        return {**info, **_unavailable("stale_common_history")}
    info["max_interval_days_observed"] = int(dates.to_series().diff().dt.days.max())
    if info["max_interval_days_observed"] > max_gap:
        return {**info, **_unavailable("gap_in_common_history")}
    return {**info, "status": "available"}


def _downside(plan, dates):
    cash, legs = plan
    value = pd.Series(cash, index=dates, dtype=float)
    for weight, closes in legs:
        prices = closes.loc[dates]
        value += weight * (prices / prices.iloc[0])
    changes = value.pct_change(fill_method=None).dropna()
    drawdowns = value / value.cummax() - 1
    trough = drawdowns.idxmin()
    worst = changes.idxmin()
    union = set().union(*(closes.loc[dates[0]:dates[-1]].index for _, closes in legs)) if legs else set(dates)
    return {"max_drawdown": float(drawdowns.loc[trough]), "peak_date": str(value.loc[:trough].idxmax().date()),
            "trough_date": str(trough.date()), "worst_interval_return": float(changes.loc[worst]),
            "evaluated_fraction_of_leg_dates": len(dates) / len(union),
            "worst_interval_start": str(dates[dates.get_loc(worst) - 1].date()), "worst_interval_end": str(worst.date())}


def compare_portfolio_risk(snapshot: dict, portfolios: dict[str, dict[str, float]], *,
                           base_currency: str, quote_currencies: dict[str, str],
                           cash_currency: str | dict[str, str] | None = None) -> dict:
    """Map portfolio IDs to invested weights. Residual cash uses its explicitly supplied currency.

    Positive-weight legs must have quotes in a known currency. FX is base units per
    foreign unit. Missing series never become flat returns. Cash is held at a flat
    nominal rate solely for this gross historical price-path diagnostic.
    """
    results = {}
    output = {
        "method": "historical_initial_weights_buy_and_hold_provider_closes",
        "base_currency": base_currency, "cash_rate_assumption": 0.0,
        "limitations": ["gross_provider_close_path", "dividend_adjustment_unverified", "fees_and_taxes_excluded",
                        "common_observed_dates_only", "cross_market_closes_may_be_asynchronous"],
        "shared_window": False, "portfolios": results,
    }
    try:
        if snapshot.get("schema_version") != "portfolio_risk_v2" or not isinstance(snapshot.get("price_history"), dict):
            raise ValueError("dated_risk_history_unavailable")
        if not base_currency:
            raise ValueError("missing_base_currency")
        start, end = [pd.Timestamp(date.fromisoformat(snapshot[k])) for k in ("lookback_start", "analysis_date")]
        minimum, max_age, max_gap = [snapshot[k] for k in ("min_observations", "max_price_age_days", "max_interval_days")]
        if (start > end or any(type(n) is not int for n in (minimum, max_age, max_gap))
                or minimum < 2 or max_age < 0 or max_gap < 1):
            raise ValueError("invalid_risk_sample_policy")
    except (ValueError, TypeError, KeyError) as exc:
        return {**output, **_unavailable(str(exc)), "portfolios": {name: _unavailable(str(exc)) for name in portfolios}}

    plans = {}
    own_dates = {}
    for name, weights in portfolios.items():
        currency = cash_currency.get(name) if isinstance(cash_currency, dict) else cash_currency
        try:
            plan = _components(snapshot, weights, quote_currencies, base_currency, currency, start, end)
            dates = _common_dates(plan[1])
            if dates is not None:
                info = _coverage(dates, end, minimum, max_age, max_gap)
                if info["status"] != "available":
                    results[name] = info
                    continue
            plans[name] = plan
            own_dates[name] = dates
        except (ValueError, TypeError, KeyError) as exc:
            results[name] = _unavailable(str(exc))

    shared = _common_dates(leg for _, legs in plans.values() for leg in legs)
    if shared is None and plans:
        # All usable plans contain base-currency cash only. Use actual benchmark dates as the observation grid.
        benchmark = snapshot.get("market_regime", {}).get("benchmark")
        try:
            shared = _series(snapshot["price_history"].get(benchmark), "benchmark_calendar", start, end).index
        except (ValueError, TypeError):
            shared = None
    window = _coverage(shared, end, minimum, max_age, max_gap)
    same_window = window["status"] == "available"
    for name, plan in plans.items():
        dates = shared if same_window else own_dates[name]
        info = window if same_window else _coverage(dates, end, minimum, max_age, max_gap)
        results[name] = {**info, **_downside(plan, dates)} if info["status"] == "available" else info

    available = sum(entry["status"] == "available" for entry in results.values())
    if not available:
        return {**output, **_unavailable("no_portfolio_with_sufficient_history")}
    if same_window:
        status = "available" if available == len(results) else "partial"
        return {**output, **window, "status": status, "shared_window": True}
    return {**output, "status": "partial", "reason": "no_shared_window_use_individual_dates"}
