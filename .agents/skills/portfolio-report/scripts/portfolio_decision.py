"""Validate explicit investment judgment without treating scores as expected returns.

Weights are fractions. This module checks contracts and arithmetic, not optimality.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

VERSION = "portfolio_decision_v1"
WORKFLOW = ["predict", "independent_investor_analysis", "risk_snapshot", "portfolio_report"]
SOURCE_STATES = {"ok", "timeout", "credentials_missing", "auth", "quota", "stale", "revision", "schema", "unavailable"}
SECRET_KEYS = {"api_key", "apikey", "access_token", "refresh_token", "password", "authorization", "secret", "token"}


def number(value, label, low=0.0, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label}: finite number required")
    if value < low or (high is not None and value > high):
        raise ValueError(f"{label}: outside [{low}, {high}]")
    return float(value)


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: nonempty text required")
    return value


def timestamp(value):
    result = datetime.fromisoformat(nonempty(value, "timestamp").replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return result.astimezone(timezone.utc)


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def safe_payload(value):
    """Reject credential fields/references instead of persisting provider secrets."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower().replace("-", "_") in SECRET_KEYS:
                raise ValueError(f"credential field forbidden: {key}")
            safe_payload(item)
    elif isinstance(value, list):
        for item in value:
            safe_payload(item)
    elif isinstance(value, str):
        if value.startswith(("https://", "http://")):
            parts = urlsplit(value)
            if parts.username or parts.password or any(k.lower() in SECRET_KEYS for k, _ in parse_qsl(parts.query)):
                raise ValueError("credential-bearing URL forbidden")
        if value.replace("\\", "/").split("/")[-1].startswith(".env"):
            raise ValueError("credential file reference forbidden")


def _source_map(doc, cutoff, created):
    sources = {}
    for src in doc["sources"]:
        sid = nonempty(src["id"], "source.id")
        if sid in sources:
            raise ValueError(f"duplicate source: {sid}")
        nonempty(src["provider"], "provider")
        nonempty(src["reference"], "reference")
        if src["status"] not in SOURCE_STATES:
            raise ValueError(f"unknown source status: {sid}")
        retrieved = timestamp(src["retrieved_at"])
        if retrieved > created:
            raise ValueError(f"retrieved after decision: {sid}")
        problems = []
        if src["status"] not in {"ok", "revision"}:
            problems.append(src["status"])
        if src["status"] in {"ok", "revision"}:
            asof = timestamp(src["as_of"])
            available = timestamp(src["available_at"])
            if asof > cutoff or available > cutoff or available > retrieved:
                raise ValueError(f"future source: {sid}")
            max_age = number(src["max_age_days"], "max_age_days")
            if (cutoff - asof).total_seconds() / 86400 > max_age:
                problems.append("stale")
            if src["status"] == "revision":
                nonempty(src["revision_reason"], "revision_reason")
        sources[sid] = {**src, "problems": problems}
    if not sources:
        raise ValueError("sources required")
    return sources


def _refs(refs, sources):
    if not isinstance(refs, list) or not refs:
        raise ValueError("nonempty source_refs required")
    for sid in refs:
        if sid not in sources:
            raise ValueError(f"unknown source reference: {sid}")
    return [f"{sid}:{problem}" for sid in refs for problem in sources[sid]["problems"]]


def _thesis(asset, sources):
    thesis = asset["thesis"]
    for key in ("rationale", "price_assumptions", "downside", "counterevidence", "review_trigger", "sizing_reason", "alternative", "missing_evidence_impact"):
        nonempty(thesis[key], f"{asset['ticker']}.thesis.{key}")
    if not isinstance(thesis["facts"], list) or not thesis["facts"]:
        raise ValueError("thesis.facts required")
    limitations = []
    for fact in thesis["facts"]:
        nonempty(fact["text"], "fact.text")
        limitations.extend(_refs(fact["source_refs"], sources))
    scenarios = thesis.get("scenarios", [])
    probabilities = []
    for scenario in scenarios:
        for key in ("assumptions", "calculation", "horizon", "currency", "return_components"):
            nonempty(scenario[key], f"scenario.{key}")
        if scenario.get("basis") != "explicit_assumptions":
            raise ValueError("scenario basis must be explicit_assumptions, not scores/confidence")
        number(scenario["target_price"], "target_price", low=0)
        limitations.extend(_refs(scenario["source_refs"], sources))
        if "probability" in scenario:
            if scenario.get("probability_kind") != "subjective_assumption":
                raise ValueError("scenario probabilities must be labelled subjective")
            probabilities.append(number(scenario["probability"], "probability", high=1))
    if probabilities and (len(probabilities) != len(scenarios) or not math.isclose(sum(probabilities), 1, abs_tol=1e-8)):
        raise ValueError("scenario probabilities must all be present and sum to one")
    return limitations


def validate_decision(document, predict, analyses, risk, investors):
    """Return a reviewable result, retaining failed proposals without executable weights."""
    safe_payload(document)
    doc = copy.deepcopy(document)
    canonical_bytes(doc)  # rejects NaN even in optional fields
    if doc["schema_version"] != VERSION:
        raise ValueError("unsupported decision schema")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", doc["decision_id"]):
        raise ValueError("invalid decision_id")
    created, cutoff = timestamp(doc["created_at"]), timestamp(doc["input_cutoff"])
    if cutoff > created:
        raise ValueError("input cutoff after decision")
    date = doc["analysis_date"]
    if date != cutoff.date().isoformat() or predict.get("analysis_date") != date or risk.get("analysis_date") != date:
        raise ValueError("predict, risk and decision dates must agree")
    regime = risk["market_regime"]
    if regime.get("as_of_date", date) > date:
        raise ValueError("future market regime")
    market_cash = number(regime["target_cash_weight"], "market cash target", high=1)
    nonempty(doc["author"], "author/model/session")
    nonempty(doc["base_currency"], "base_currency")
    user = doc["user_context"]
    for key in ("objective", "evaluation_horizon", "spending_horizon", "spending_currency", "risk_tolerance"):
        nonempty(user[key], f"user_context.{key}")
    if user["holdings"] != "unknown" and not isinstance(user["holdings"], dict):
        raise ValueError("holdings must be unknown or a mapping")
    if isinstance(user["holdings"], dict):
        for ticker, value in user["holdings"].items():
            if ticker != ticker.upper():
                raise ValueError("holding ticker must be canonical")
            number(value, f"holdings.{ticker}", high=1)
        if sum(user["holdings"].values()) > 1 + 1e-8:
            raise ValueError("existing holding weights exceed one")
    liquidity = number(user["liquidity_min_weight"], "liquidity_min_weight", high=1)
    if user["liquidity_basis"] not in {"user_confirmed", "assumption"}:
        raise ValueError("liquidity_basis required")
    if user["required_amount"] is not None:
        amount = number(user["required_amount"], "required_amount")
        capital = number(user["portfolio_value"], "portfolio_value", low=1e-12)
        fx = number(user["spending_fx_to_base"], "spending_fx_to_base", low=1e-12)
        nonempty(user["spending_fx_basis"], "spending_fx_basis")
        if liquidity + 1e-8 < amount * fx / capital:
            raise ValueError("liquidity weight contradicts required amount")
    elif user["spending_horizon"] != "none" and user["liquidity_basis"] != "assumption":
        raise ValueError("unknown spending amount requires an explicit liquidity assumption")
    nonempty(user["liquidity_reason"], "liquidity_reason")
    sources = _source_map(doc, cutoff, created)
    limitations, blocked, violations = [], [], []
    if user["liquidity_basis"] == "assumption":
        limitations.append("liquidity reserve is an assumption")
    policy = doc["constraints"]
    stock_cap = number(policy.get("max_stock_weight", .15), "max_stock_weight", high=1)
    etf_cap = number(policy.get("max_diversified_etf_weight", 1), "max_diversified_etf_weight", high=1)
    sector_cap = number(policy.get("max_direct_sector_weight", .35), "max_direct_sector_weight", high=1)
    nonempty(policy["rationale"], "constraints.rationale")
    overrides = policy.get("asset_caps", {})
    for key, value in overrides.items():
        number(value, f"asset cap {key}", high=1)
    assets, weights, evidence = {}, {}, {}
    issuers, sectors, direct_sectors = defaultdict(float), defaultdict(float), defaultdict(float)
    coverage = 0.0
    ranking_tickers = {s["ticker"] for s in predict.get("rankings", [])}
    if not investors or len(set(investors)) != len(investors):
        raise ValueError("unique independent investor list required")
    for asset in doc["assets"]:
        ticker = nonempty(asset["ticker"], "ticker")
        if ticker != ticker.upper() or ticker in assets:
            raise ValueError(f"duplicate or noncanonical ticker: {ticker}")
        if asset["asset_type"] not in {"stock", "etf"}:
            raise ValueError(f"unsupported asset type: {ticker}")
        weight = number(asset["weight"], f"{ticker}.weight", high=1)
        if not math.isclose(weight, round(weight, 4), abs_tol=1e-10):
            raise ValueError("weights must use at most four decimal places (0.01%)")
        assets[ticker] = asset
        nonempty(asset["selection_reason"], "selection_reason")
        quote = asset["quote"]
        quote_problems = _refs([quote["source_id"]], sources)
        if not quote_problems:
            number(quote["value"], f"{ticker}.price", low=1e-12)
            quote_time = timestamp(quote["as_of"])
            quote_source = sources[quote["source_id"]]
            if quote_time != timestamp(quote_source["as_of"]):
                raise ValueError(f"quote/source timestamp mismatch: {ticker}")
        nonempty(quote["currency"], "quote currency")
        nonempty(asset["calendar"], "calendar")
        if weight == 0:
            evidence[ticker] = {"price_issues": quote_problems, "selection_reason": asset["selection_reason"]}
            continue
        weights[ticker] = weight
        blocked.extend(f"{ticker}: {p}" for p in quote_problems)
        limitations.extend(_thesis(asset, sources))
        if asset["asset_type"] == "stock" and ticker not in ranking_tickers:
            raise ValueError(f"stock missing from predict universe: {ticker}")
        opinions = {}
        for investor in investors:
            opinion = copy.deepcopy(analyses.get(ticker, {}).get(investor))
            if not opinion:
                raise ValueError(f"independent analysis missing: {ticker}/{investor}")
            if opinion.get("analysis_source") != "independent_investor_analysis":
                raise ValueError("analysis source must be independent")
            if opinion.get("analysis_date", date) != date:
                raise ValueError("independent opinion date mismatch")
            if opinion["signal"] not in {"bullish", "neutral", "bearish", "abstain"}:
                raise ValueError("invalid independent signal")
            number(opinion["confidence"], "confidence", high=100)
            nonempty(opinion["reasoning"], "reasoning")
            if opinion["data_quality"] not in {"complete", "partial", "insufficient"}:
                raise ValueError("invalid data quality")
            if opinion["data_quality"] != "complete":
                limitations.append(f"{ticker}/{investor}: {opinion['data_quality']}; see missing_evidence_impact")
            opinion["analysis_source"] = "independent_investor_analysis"
            opinions[investor] = opinion
        vol = risk.get("annualized_volatility", {}).get(ticker)
        if vol is None:
            limitations.append(f"{ticker}: risk volatility unavailable; see missing_evidence_impact")
        else:
            number(vol, "volatility")
        evidence[ticker] = {"independent_analyses": opinions, "annualized_volatility": vol, "price_issues": quote_problems}
        if asset["asset_type"] == "stock":
            cap = overrides.get(ticker, stock_cap)
            sector = nonempty(asset["sector"], "stock sector")
            issuer = nonempty(asset["issuer"], "stock issuer")
            direct_sectors[sector] += weight
            issuers[issuer] += weight
            sectors[sector] += weight
            coverage += weight
        else:
            etf = asset["etf"]
            for key in ("index", "concentration"):
                nonempty(etf[key], f"etf.{key}")
            number(etf["expense_ratio"], "expense_ratio", high=1)
            leverage = number(etf["leverage"], "leverage", low=-10, high=10)
            if not isinstance(etf["diversified"], bool) or not isinstance(etf["holdings_complete"], bool):
                raise ValueError("ETF diversified/holdings_complete must be boolean")
            if not etf["diversified"] or leverage != 1:
                if ticker not in overrides:
                    raise ValueError(f"concentrated/leveraged ETF needs explicit asset cap: {ticker}")
            cap = overrides.get(ticker, etf_cap)
            holdings_problems = _refs([etf["source_id"]], sources)
            if timestamp(etf["holdings_as_of"]) != timestamp(sources[etf["source_id"]]["as_of"]):
                raise ValueError("ETF holdings/source timestamp mismatch")
            known_weight = 0.0
            holding_tickers = set()
            for holding in etf["holdings"]:
                ht = nonempty(holding["ticker"], "holding ticker")
                if ht in holding_tickers:
                    raise ValueError("duplicate ETF holding")
                holding_tickers.add(ht)
                hw = number(holding["weight"], "holding weight", high=1)
                known_weight += hw
                issuer = nonempty(holding["issuer"], "holding issuer")
                sector = nonempty(holding["sector"], "holding sector")
                if not holdings_problems:
                    issuers[issuer] += weight * hw
                    sectors[sector] += weight * hw
            if known_weight > 1 + 1e-8 or (etf["holdings_complete"] and not math.isclose(known_weight, 1, abs_tol=1e-8)):
                raise ValueError("ETF holdings weights inconsistent with coverage")
            if holdings_problems or not etf["holdings_complete"]:
                limitations.append(f"{ticker}: incomplete ETF look-through")
            if not holdings_problems:
                coverage += weight * known_weight
        if weight > cap + 1e-8:
            violations.append(f"{ticker}: {weight} exceeds asset cap {cap}")
    if not assets or doc["benchmark"] not in assets:
        raise ValueError("comparison benchmark must be included in assets, even at zero weight")
    if isinstance(user["holdings"], dict):
        unreviewed = {ticker for ticker, weight in user["holdings"].items() if ticker != "CASH" and weight > 0} - set(assets)
        if unreviewed:
            raise ValueError(f"existing holdings need explicit review: {sorted(unreviewed)}")
    benchmark = assets[doc["benchmark"]]
    blocked.extend(f"benchmark: {p}" for p in _refs([benchmark["quote"]["source_id"]], sources))
    for ticker in set(overrides) - set(assets):
        raise ValueError(f"asset cap references unknown ticker: {ticker}")
    for sector, weight in direct_sectors.items():
        if weight > sector_cap + 1e-8:
            violations.append(f"direct sector {sector}: {weight} exceeds {sector_cap}")
    invested = sum(weights.values())
    for field, exposure in (("max_total_issuer_weight", issuers), ("max_total_sector_weight", sectors)):
        if field in policy:
            cap = number(policy[field], field, high=1)
            if coverage + 1e-8 < invested:
                blocked.append(f"{field}: incomplete look-through")
            violations.extend(f"{field}/{key}: {value} exceeds {cap}" for key, value in exposure.items() if value > cap + 1e-8)
    cash = doc["cash"]
    cash_weight = number(cash["weight"], "cash weight", high=1)
    for field in ("currency", "rationale", "opportunity_cost", "liquidity_reason", "strategic_reason", "market_regime_reason"):
        nonempty(cash[field], f"cash.{field}")
    number(cash["annual_rate"], "cash annual_rate", low=-.99, high=1)
    number(cash["liquidity_weight"], "cash liquidity_weight", high=1)
    if cash["liquidity_weight"] > cash_weight + 1e-8 or cash["liquidity_weight"] < liquidity - 1e-8:
        violations.append("cash does not meet liquidity reserve")
    if cash["currency"] != user["spending_currency"] and liquidity > 0:
        nonempty(cash["liquidity_fx_plan"], "liquidity_fx_plan")
        limitations.append("liquidity reserve has currency risk; see liquidity_fx_plan")
    if not math.isclose(cash_weight, round(cash_weight, 4), abs_tol=1e-10) or not math.isclose(invested + cash_weight, 1, abs_tol=1e-8):
        violations.append("final allocation must total 100.00% without unallocated residual")
    rules = doc["evaluation"]
    if rules["method"] != "initial_weights_buy_and_hold" or rules["dividends"] != "reinvested" or rules["tax_basis"] != "pre_tax":
        raise ValueError("unsupported evaluation method/dividend/tax convention")
    if timestamp(rules["review_at"]) <= created:
        raise ValueError("review_at must follow decision")
    for key in ("entry_cost_bps", "exit_cost_bps", "fx_cost_bps"):
        number(rules[key], key, high=10000)
    foreign = cash["currency"] != doc["base_currency"] or any(a["quote"]["currency"] != doc["base_currency"] for a in assets.values())
    if rules["exit_cost_bps"] + (rules["fx_cost_bps"] if foreign else 0) >= 10000:
        raise ValueError("combined exit costs must be below 100%")
    nonempty(rules["cost_assumptions"], "cost_assumptions")
    nonempty(rules["review_trigger"], "review_trigger")
    # Do not let a declarative evidence label become a manufactured performance claim.
    performance = {"status": "prior_only", "scope": "current decision; prospective record required"}
    limitations.extend(f"{sid}: {','.join(src['problems'])}" for sid, src in sources.items() if src["problems"])
    status = "blocked_input" if blocked else "infeasible" if violations else "conditional" if limitations else "ready"
    actions = {}
    if status in {"ready", "conditional"}:
        if user["holdings"] == "unknown":
            actions = {ticker: {"action": "target_only", "target_weight": weight} for ticker, weight in weights.items()}
        else:
            for ticker in sorted((set(weights) | set(user["holdings"])) - {"CASH"}):
                current, target = user["holdings"].get(ticker, 0), weights.get(ticker, 0)
                action = "hold" if math.isclose(current, target, abs_tol=1e-8) else "exit" if target == 0 else "add" if target > current else "reduce"
                actions[ticker] = {"action": action, "current_weight": current, "target_weight": target, "change_weight": target - current}
    return {
        "schema_version": VERSION, "methodology": "explicit_investment_judgment_v1",
        "decision_id": doc["decision_id"], "analysis_date": date, "created_at": doc["created_at"],
        "status": status, "weights": weights if status in {"ready", "conditional"} else {},
        "cash_weight": cash_weight if status in {"ready", "conditional"} else None,
        "actions": actions,
        "decision": doc, "performance_evidence": performance,
        "constraint_checks": {"valid": not blocked and not violations, "violations": violations, "input_issues": blocked,
                              "direct_sectors": dict(direct_sectors), "total_issuers": dict(issuers), "total_sectors": dict(sectors),
                              "lookthrough_coverage_weight": coverage},
        "evidence": evidence, "limitations": sorted(set(limitations)),
        "market_regime": {**regime, "usage": "advisory", "cash_difference": cash_weight - market_cash},
        "risk_snapshot": copy.deepcopy(risk),
        "research_provenance": {"workflow": WORKFLOW, "factor_policy": predict.get("factor_weight_policy", {}),
                                "news_policy": predict.get("news_sentiment_policy", {}), "sources": list(sources.values()),
                                "input_hashes": {"predict": digest(predict), "independent_analyses": digest(analyses), "risk": digest(risk)}},
    }


def save_snapshot(result, root):
    safe_payload(result)
    decision_id = result["decision_id"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", decision_id):
        raise ValueError("invalid decision_id")
    if result["decision"]["decision_id"] != decision_id or result["schema_version"] != VERSION:
        raise ValueError("snapshot identity/schema mismatch")
    root = Path(root)
    previous = result["decision"].get("previous_decision_id")
    if previous:
        if previous == decision_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", previous):
            raise ValueError("invalid previous decision id")
        load_snapshot(root / previous)
    folder = root / decision_id
    folder.mkdir(parents=True, exist_ok=False)
    body = canonical_bytes(result)
    (folder / "decision.json").write_bytes(body)
    (folder / "manifest.json").write_bytes(canonical_bytes({"decision_id": decision_id, "sha256": hashlib.sha256(body).hexdigest(),
        "created_at": result["created_at"], "schema_version": VERSION, "previous_decision_id": previous,
        "input_hashes": result["research_provenance"]["input_hashes"]}))
    return folder


def load_snapshot(folder):
    folder = Path(folder)
    body = (folder / "decision.json").read_bytes()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(body).hexdigest() != manifest["sha256"]:
        raise ValueError("decision snapshot integrity mismatch")
    result = json.loads(body)
    if result["decision_id"] != manifest["decision_id"] or result["decision_id"] != folder.name:
        raise ValueError("snapshot identity mismatch")
    return result
