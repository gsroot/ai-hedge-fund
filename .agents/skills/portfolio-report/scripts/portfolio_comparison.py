"""Compare explicit allocations on the same mandate, assumptions and cost basis."""
from __future__ import annotations

import math

from portfolio_decision import MissingAssetCap, _refs, allocation_exposure, nonempty, number


def _positive(weights):
    return {ticker: weight for ticker, weight in weights.items() if weight > 0}


def _plans(doc, assets):
    benchmark = doc["benchmark"]
    if assets[benchmark]["asset_type"] != "etf":
        raise ValueError("v2 benchmark must be an investable ETF")
    user = doc["user_context"]
    reserve = user["liquidity_min_weight"]
    holdings = user["holdings"]
    complete = isinstance(holdings, dict) and math.isclose(sum(holdings.values()), 1, abs_tol=1e-8)
    if complete and holdings.get("CASH", 0) > 0:
        complete = user.get("current_cash_currency") == doc["cash"]["currency"]
    selected = _positive({ticker: asset["weight"] for ticker, asset in assets.items()})
    if doc["cash"]["weight"]:
        selected["CASH"] = doc["cash"]["weight"]
    plans = {"selected": selected,
             "benchmark_reserve": _positive({benchmark: 1 - reserve, "CASH": reserve}),
             "all_cash": {"CASH": 1.0},
             "current": _positive(holdings) if complete else None}
    active_positions = {ticker: weight for ticker, weight in selected.items() if ticker not in {"CASH", benchmark}}
    if active_positions:
        half = {**selected, **{ticker: weight / 2 for ticker, weight in active_positions.items()}}
        # Target weights have four decimal places; an exact half needs at most five.
        half[benchmark] = round(selected.get(benchmark, 0) + sum(active_positions.values()) / 2, 5)
        plans["half_active_tilt"] = half
    return plans


def _transition(current, target, assets, doc):
    if current is None or target is None:
        return {"status": "unavailable", "reason": "complete holdings and comparable current cash currency required"}
    changes = {ticker: target.get(ticker, 0) - current.get(ticker, 0) for ticker in set(current) | set(target)}
    securities = {ticker: delta for ticker, delta in sorted(changes.items()) if ticker != "CASH"}
    bought = sum(max(delta, 0) for delta in securities.values())
    sold = sum(max(-delta, 0) for delta in securities.values())
    turnover = sum(abs(delta) for delta in changes.values()) / 2
    metrics = {"one_way_turnover": turnover, "buy_weight": bought, "sell_weight": sold}
    if doc["cash"]["currency"] != doc["base_currency"] and turnover > 1e-12:
        return {**metrics, "status": "unavailable", "reason": "foreign-currency funding path unknown"}
    rules = doc["evaluation"]
    foreign = sum(abs(delta) for ticker, delta in securities.items()
                  if assets[ticker]["quote"]["currency"] != doc["base_currency"])
    cost = (bought * rules["entry_cost_bps"] + sold * rules["exit_cost_bps"] + foreign * rules["fx_cost_bps"]) / 10000
    if cost >= 1:
        return {**metrics, "status": "unavailable", "reason": "estimated transition costs consume portfolio"}
    return {**metrics, "status": "estimated", "estimated_cost_weight": cost}


def _scenarios(comparison, assets, sources):
    cases = comparison["scenarios"]
    if not isinstance(cases, dict) or set(cases) != {"base", "downside"}:
        raise ValueError("comparison.scenarios requires base and downside")
    for name, case in cases.items():
        nonempty(case["assumptions"], f"{name}.assumptions")
        issues = _refs(case["source_refs"], sources)
        if issues and case["returns"]:
            raise ValueError(f"{name}: numeric assumptions reference unavailable evidence: {issues}")
        returns = case["returns"]
        if not isinstance(returns, dict) or set(returns) - (set(assets) | {"CASH"}):
            raise ValueError(f"{name}: returns must map reviewed tickers or CASH to assumed total returns")
        for ticker, value in returns.items():
            number(value, f"{name}.{ticker}.return", low=-1)
    return cases


def _scenario_result(case, weights, transition):
    missing = sorted(set(weights) - set(case["returns"]))
    if missing:
        return {"status": "unavailable", "missing": missing}
    gross = sum(weight * case["returns"][ticker] for ticker, weight in weights.items())
    cost = transition.get("estimated_cost_weight")
    return {"status": "estimated", "gross_return": gross,
            "after_transition_return": None if cost is None else (1 - cost) * (1 + gross) - 1}


def _spending_reserve(weights, transition, doc):
    user = doc["user_context"]
    if user["required_amount"] is None:
        return {"status": "not_applicable"}
    required = user["required_amount"] * user["spending_fx_to_base"]
    capital = user["portfolio_value"]
    cash = weights.get("CASH", 0)
    cost = transition.get("estimated_cost_weight")
    if cost is not None:
        basis = "estimated_transition_cost"
    elif required == 0:
        return {"status": "satisfied", "required_base_amount": 0}
    else:
        # Without a funding path the account might need to sell every existing security.
        # Bound the modeled one-time buy/sell/FX fees before certifying a monetary reserve.
        if doc["cash"]["currency"] != doc["base_currency"]:
            return {"status": "unavailable", "reason": "foreign cash funding path required",
                    "required_base_amount": required}
        rules = doc["evaluation"]
        buy_cost = (1 - cash) * (rules["entry_cost_bps"] + rules["fx_cost_bps"])
        cost = min(1, (buy_cost + rules["exit_cost_bps"] + rules["fx_cost_bps"]) / 10000)
        basis = "conservative_transition_cost_bound"
    available = cash * capital * (1 - cost)
    status = "satisfied"
    if available + 1e-8 < required:
        status = "unavailable" if basis == "conservative_transition_cost_bound" else "violated"
    return {"status": status, "basis": basis, "required_base_amount": required,
            "available_base_amount_after_cost": available}


def _constraint_issues(weights, doc, assets, sources):
    risky = {ticker: weight for ticker, weight in weights.items() if ticker != "CASH"}
    issues = [f"{ticker}: {p}" for ticker in risky for p in _refs([assets[ticker]["quote"]["source_id"]], sources)]
    violations = []
    limitations = []
    try:
        check = allocation_exposure(risky, assets, doc["constraints"], sources)
    except KeyError as exc:
        # A sold holding or a zero-weight fund can lack metadata needed only by the alternative.
        issues.append(f"alternative exposure input missing: {exc}")
    except MissingAssetCap as exc:
        issues.append(str(exc))
    else:
        issues.extend(check["input_issues"])
        violations.extend(check["violations"])
        limitations.extend(check["limitations"])
    if weights.get("CASH", 0) < doc["user_context"]["liquidity_min_weight"] - 1e-8:
        violations.append("cash below minimum reserve")
    return issues, violations, limitations


def build_comparison(doc, assets, sources, risk, selected_issues, selected_violations, *, preview=False):
    from portfolio_risk import compare_portfolio_risk

    plans = _plans(doc, assets)
    current = plans["current"]
    judgment = doc["comparison"]
    cases = _scenarios(judgment, assets, sources)
    reviews = judgment.get("reviews", {}) if preview else judgment["reviews"]
    required = {key for key, weights in plans.items() if key != "selected" and weights is not None}
    if not isinstance(reviews, dict) or set(reviews) - (set(plans) - {"selected"}) or (not preview and required - set(reviews)):
        raise ValueError(f"comparison.reviews must address all applicable alternatives: {sorted(required)}")
    for key, review in reviews.items():
        nonempty(review["tradeoff"], f"{key}.tradeoff")
        nonempty(review["switch_condition"], f"{key}.switch_condition")

    loss_limit = doc["constraints"].get("max_downside_scenario_loss")
    if loss_limit is not None:
        number(loss_limit, "max_downside_scenario_loss", high=1)
    portfolios = {}
    limitations = []
    for key, weights in plans.items():
        transition = _transition(current, weights, assets, doc)
        if weights is None:
            portfolios[key] = {"status": "unavailable", "weights": None, "transition": transition,
                               "input_issues": [transition["reason"]], "violations": []}
            continue
        if key == "selected":
            issues, violations, row_limits = list(selected_issues), list(selected_violations), []
        else:
            issues, violations, row_limits = _constraint_issues(weights, doc, assets, sources)
        # The chosen basket may liquidate a holding for which no current quote was supplied.
        if current is not None:
            for ticker, original in current.items():
                if ticker != "CASH" and original > weights.get(ticker, 0) + 1e-8:
                    issues.extend(f"sale {ticker}: {p}" for p in _refs([assets[ticker]["quote"]["source_id"]], sources))
        outcomes = {name: _scenario_result(case, weights, transition) for name, case in cases.items()}
        reserve = _spending_reserve(weights, transition, doc)
        if reserve["status"] == "violated":
            violations.append("cash after estimated transition cost is below required spending amount")
        elif reserve["status"] == "unavailable":
            issues.append("cannot verify required spending amount after transition cost")
        downside = outcomes["downside"].get("gross_return")
        if loss_limit is not None:
            if downside is None:
                issues.append("max_downside_scenario_loss requires a complete downside scenario")
            elif downside < -loss_limit - 1e-8:
                violations.append("gross downside scenario exceeds specified loss threshold")
        status = "unavailable" if issues else "infeasible" if violations else "feasible"
        portfolios[key] = {"status": status, "weights": weights, "transition": transition,
                           "spending_reserve": reserve, "limitations": row_limits,
                           "violations": violations, "input_issues": issues, "scenarios": outcomes}
        if key == "selected":
            if transition["status"] == "unavailable":
                limitations.append(f"transition cost unavailable: {transition['reason']}")
            limitations.extend(f"{name} scenario unquantified for selected basket"
                               for name, scenario in outcomes.items() if scenario["status"] == "unavailable")

    feasible = {key: {ticker: weight for ticker, weight in row["weights"].items() if ticker != "CASH"}
                for key, row in portfolios.items() if row["status"] == "feasible"}
    historical = (compare_portfolio_risk(risk, feasible, base_currency=doc["base_currency"],
                                         quote_currencies={t: a["quote"]["currency"] for t, a in assets.items()},
                                         cash_currency=doc["cash"]["currency"])
                  if feasible else {"status": "unavailable", "reason": "no feasible basket", "portfolios": {}})
    if historical.get("portfolios", {}).get("selected", {}).get("status") != "available":
        limitations.append("selected basket historical risk comparison unavailable")
    return {"portfolios": portfolios, "historical_risk": historical, "reviews": reviews,
            "scenario_basis": "subjective_total_returns_in_base_currency", "horizon": doc["user_context"]["evaluation_horizon"],
            "limitations": limitations}
