#!/usr/bin/env python3
"""Point-in-time US fundamentals from SEC EDGAR Company Facts.

Facts are filtered by their public ``filed`` date. A later restatement is visible
only after its own filing date, so the module can be used in historical research
without substituting today's Yahoo snapshot for past fundamentals.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx
import pandas as pd
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(PROJECT_ROOT / ".env", override=False)


SEC_COMPANYFACTS_URL = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
)
DEFAULT_SEC_USER_AGENT = "ai-hedge-fund/1.0 point-in-time research gsr27"

# Historical Dow universe used by the walk-forward validator. CIK is stable across
# ticker changes where the reporting entity continued (for example UTX -> RTX).
CIK_BY_TICKER = {
    "AAPL": 320193,
    "AMGN": 318154,
    "AMZN": 1018724,
    "AXP": 4962,
    "BA": 12927,
    "CAT": 18230,
    "CRM": 1108524,
    "CSCO": 858877,
    "CVX": 93410,
    "DD": 1666700,
    "DIS": 1744489,
    "DOW": 1751788,
    "GE": 40545,
    "GOOGL": 1652044,
    "GS": 886982,
    "HD": 354950,
    "HON": 773840,
    "IBM": 51143,
    "INTC": 50863,
    "JNJ": 200406,
    "JPM": 19617,
    "KO": 21344,
    "MCD": 63908,
    "MMM": 66740,
    "MRK": 310158,
    "MSFT": 789019,
    "NKE": 320187,
    "NVDA": 1045810,
    "PFE": 78003,
    "PG": 80424,
    "RTX": 101829,
    "SHW": 89800,
    "T": 732717,
    "TRV": 86312,
    "UNH": 731766,
    "V": 1403161,
    "VZ": 732712,
    "WBA": 1618921,
    "WMT": 104169,
    "XOM": 34088,
}

# Legal reporting-entity changes. The effective date controls which issuer's
# filings were actually available for the historical constituent represented by
# the continuous research ticker.
CIK_HISTORY_BY_TICKER = {
    "DD": (("1900-01-01", 30554), ("2017-09-01", 1666700)),
    "DIS": (("1900-01-01", 1001039), ("2019-03-20", 1744489)),
}

DURATION_CONCEPTS = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_income": ("OperatingIncomeLoss",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditure": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForAdditionsToPropertyPlantAndEquipment",
    ),
}

INSTANT_CONCEPTS = {
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
}

SHARE_CONCEPTS = (
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesOutstanding"),
)


def sec_user_agent() -> str:
    return os.getenv("SEC_USER_AGENT", DEFAULT_SEC_USER_AGENT).strip()


def cik_for_ticker(ticker: str, as_of: str | pd.Timestamp | None = None) -> int:
    ticker = ticker.upper()
    history = CIK_HISTORY_BY_TICKER.get(ticker)
    if not history or as_of is None:
        return CIK_BY_TICKER[ticker]
    cutoff = pd.Timestamp(as_of).normalize()
    eligible = [cik for effective_date, cik in history if pd.Timestamp(effective_date) <= cutoff]
    if not eligible:
        raise ValueError(f"No CIK mapping for {ticker} as of {cutoff:%Y-%m-%d}")
    return eligible[-1]


def _all_ciks(ticker: str) -> list[int]:
    ticker = ticker.upper()
    history = CIK_HISTORY_BY_TICKER.get(ticker)
    return sorted({cik for _, cik in history}) if history else [CIK_BY_TICKER[ticker]]


def _cache_path(cache_dir: Path, ticker: str, cik: int | None = None) -> Path:
    ticker = ticker.upper()
    resolved_cik = cik if cik is not None else CIK_BY_TICKER[ticker]
    return cache_dir / f"{ticker}_{resolved_cik:010d}.json"


def download_companyfacts(
    tickers: Iterable[str],
    cache_dir: Path,
    refresh: bool = False,
    request_interval_seconds: float = 0.12,
) -> dict[str, Any]:
    """Download one SEC Company Facts JSON per ticker and write a hash manifest."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    requested = sorted(set(ticker.upper() for ticker in tickers))
    unknown = [ticker for ticker in requested if ticker not in CIK_BY_TICKER]
    if unknown:
        raise ValueError(f"CIK mapping missing for: {', '.join(unknown)}")
    downloaded = []
    reused = []
    failed = {}
    headers = {
        "User-Agent": sec_user_agent(),
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json",
    }
    with httpx.Client(headers=headers, timeout=60.0, follow_redirects=True) as client:
        for ticker in requested:
            for cik in _all_ciks(ticker):
                cache_key = f"{ticker}:{cik}"
                path = _cache_path(cache_dir, ticker, cik)
                if path.exists() and not refresh:
                    reused.append(cache_key)
                    continue
                url = SEC_COMPANYFACTS_URL.format(cik=cik)
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get("cik") != cik:
                        raise ValueError("CIK mismatch in SEC response")
                    path.write_text(
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8",
                    )
                    downloaded.append(cache_key)
                except Exception as exc:
                    failed[cache_key] = str(exc)
                time.sleep(max(0.0, request_interval_seconds))

    files = {}
    for ticker in requested:
        for cik in _all_ciks(ticker):
            path = _cache_path(cache_dir, ticker, cik)
            if path.exists():
                files[f"{ticker}:{cik}"] = {
                    "path": str(path.resolve()),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                }
    manifest = {
        "source": "SEC EDGAR Company Facts API",
        "endpoint": SEC_COMPANYFACTS_URL,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested": requested,
        "downloaded": downloaded,
        "reused": reused,
        "failed": failed,
        "files": files,
    }
    (cache_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def load_companyfacts(
    cache_dir: Path, ticker: str, as_of: str | pd.Timestamp | None = None
) -> dict[str, Any]:
    resolved_cik = cik_for_ticker(ticker, as_of)
    path = _cache_path(cache_dir, ticker.upper(), resolved_cik)
    if not path.exists():
        raise FileNotFoundError(f"SEC Company Facts cache not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("cik") != resolved_cik:
        raise ValueError(f"SEC cache CIK mismatch for {ticker}")
    return payload


def _fact_entries(
    payload: dict[str, Any], taxonomy: str, concept: str, unit: str
) -> list[dict[str, Any]]:
    fact = payload.get("facts", {}).get(taxonomy, {}).get(concept, {})
    return list(fact.get("units", {}).get(unit, []))


def _valid_filed(entry: dict[str, Any], as_of: pd.Timestamp) -> bool:
    filed = entry.get("filed")
    if not filed:
        return False
    try:
        return pd.Timestamp(filed).normalize() <= as_of
    except Exception:
        return False


def _annual_duration_history(
    payload: dict[str, Any],
    concepts: Iterable[str],
    as_of: str | pd.Timestamp,
) -> list[dict[str, Any]]:
    cutoff = pd.Timestamp(as_of).normalize()
    candidates = []
    concept_priority = {concept: index for index, concept in enumerate(concepts)}
    for concept in concepts:
        for entry in _fact_entries(payload, "us-gaap", concept, "USD"):
            if entry.get("form") not in {"10-K", "10-K/A"}:
                continue
            if entry.get("fp") not in {None, "FY"} or not _valid_filed(entry, cutoff):
                continue
            if not entry.get("start") or not entry.get("end"):
                continue
            try:
                duration = (pd.Timestamp(entry["end"]) - pd.Timestamp(entry["start"])).days
                value = float(entry["val"])
            except Exception:
                continue
            if not 300 <= duration <= 450 or not math_is_finite(value):
                continue
            candidates.append(
                {
                    **entry,
                    "value": value,
                    "concept": concept,
                    "concept_priority": concept_priority[concept],
                }
            )

    by_period: dict[str, dict[str, Any]] = {}
    for entry in candidates:
        period = entry["end"]
        current = by_period.get(period)
        key = (pd.Timestamp(entry["filed"]), -entry["concept_priority"])
        if current is None:
            by_period[period] = entry
            continue
        current_key = (
            pd.Timestamp(current["filed"]),
            -current["concept_priority"],
        )
        if key > current_key:
            by_period[period] = entry
    return sorted(by_period.values(), key=lambda entry: entry["end"])


def _annual_instant_history(
    payload: dict[str, Any],
    concepts: Iterable[str],
    as_of: str | pd.Timestamp,
) -> list[dict[str, Any]]:
    cutoff = pd.Timestamp(as_of).normalize()
    candidates = []
    concept_priority = {concept: index for index, concept in enumerate(concepts)}
    for concept in concepts:
        for entry in _fact_entries(payload, "us-gaap", concept, "USD"):
            if entry.get("form") not in {"10-K", "10-K/A"}:
                continue
            if entry.get("fp") not in {None, "FY"} or not _valid_filed(entry, cutoff):
                continue
            if not entry.get("end"):
                continue
            try:
                value = float(entry["val"])
            except Exception:
                continue
            if not math_is_finite(value):
                continue
            candidates.append(
                {
                    **entry,
                    "value": value,
                    "concept": concept,
                    "concept_priority": concept_priority[concept],
                }
            )
    by_period: dict[str, dict[str, Any]] = {}
    for entry in candidates:
        period = entry["end"]
        current = by_period.get(period)
        key = (pd.Timestamp(entry["filed"]), -entry["concept_priority"])
        if current is None or key > (
            pd.Timestamp(current["filed"]),
            -current["concept_priority"],
        ):
            by_period[period] = entry
    return sorted(by_period.values(), key=lambda entry: entry["end"])


def _shares_history(
    payload: dict[str, Any], as_of: str | pd.Timestamp
) -> list[dict[str, Any]]:
    cutoff = pd.Timestamp(as_of).normalize()
    candidates = []
    for priority, (taxonomy, concept) in enumerate(SHARE_CONCEPTS):
        for entry in _fact_entries(payload, taxonomy, concept, "shares"):
            if entry.get("form") not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}:
                continue
            if not _valid_filed(entry, cutoff) or not entry.get("end"):
                continue
            try:
                value = float(entry["val"])
            except Exception:
                continue
            if value <= 0 or not math_is_finite(value):
                continue
            candidates.append(
                {**entry, "value": value, "concept": concept, "concept_priority": priority}
            )
    by_period: dict[str, dict[str, Any]] = {}
    for entry in candidates:
        period = entry["end"]
        current = by_period.get(period)
        key = (pd.Timestamp(entry["filed"]), -entry["concept_priority"])
        if current is None or key > (
            pd.Timestamp(current["filed"]),
            -current["concept_priority"],
        ):
            by_period[period] = entry
    return sorted(by_period.values(), key=lambda entry: (entry["filed"], entry["end"]))


def math_is_finite(value: float) -> bool:
    return value == value and value not in {float("inf"), float("-inf")}


def _latest(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    return history[-1] if history else None


def _growth(history: list[dict[str, Any]]) -> float | None:
    if len(history) < 2:
        return None
    current = history[-1]["value"]
    previous = history[-2]["value"]
    if previous == 0:
        return None
    return current / abs(previous) - 1.0


def fundamental_snapshot(
    payload: dict[str, Any],
    as_of: str | pd.Timestamp,
    raw_market_price: float | None,
) -> dict[str, Any]:
    """Build a reproducible annual-fundamental snapshot known on ``as_of``."""
    cutoff = pd.Timestamp(as_of).normalize()
    duration_histories = {
        name: _annual_duration_history(payload, concepts, cutoff)
        for name, concepts in DURATION_CONCEPTS.items()
    }
    instant_histories = {
        name: _annual_instant_history(payload, concepts, cutoff)
        for name, concepts in INSTANT_CONCEPTS.items()
    }
    shares_history = _shares_history(payload, cutoff)
    selected = {
        name: _latest(history)
        for name, history in {**duration_histories, **instant_histories}.items()
    }
    selected["shares_outstanding"] = _latest(shares_history)

    values = {
        name: (entry["value"] if entry else None) for name, entry in selected.items()
    }
    shares = values["shares_outstanding"]
    market_cap = (
        float(raw_market_price) * shares
        if raw_market_price is not None and raw_market_price > 0 and shares
        else None
    )
    revenue = values["revenue"]
    net_income = values["net_income"]
    operating_income = values["operating_income"]
    operating_cash_flow = values["operating_cash_flow"]
    capex = values["capital_expenditure"]
    assets = values["assets"]
    liabilities = values["liabilities"]
    equity = values["equity"]
    free_cash_flow = (
        operating_cash_flow - capex
        if operating_cash_flow is not None and capex is not None
        else None
    )

    def safe_ratio(numerator, denominator):
        if numerator is None or denominator is None or denominator == 0:
            return None
        return numerator / denominator

    metrics = {
        "market_cap": market_cap,
        "earnings_yield": safe_ratio(net_income, market_cap),
        "free_cash_flow_yield": safe_ratio(free_cash_flow, market_cap),
        "sales_yield": safe_ratio(revenue, market_cap),
        "return_on_assets": safe_ratio(net_income, assets),
        "return_on_equity": safe_ratio(net_income, equity),
        "operating_margin": safe_ratio(operating_income, revenue),
        "free_cash_flow_margin": safe_ratio(free_cash_flow, revenue),
        "liabilities_to_assets": safe_ratio(liabilities, assets),
        "cash_conversion": safe_ratio(operating_cash_flow, net_income),
        "accruals_to_assets": safe_ratio(
            net_income - operating_cash_flow
            if net_income is not None and operating_cash_flow is not None
            else None,
            assets,
        ),
        "revenue_growth": _growth(duration_histories["revenue"]),
        "net_income_growth": _growth(duration_histories["net_income"]),
    }
    available_core = sum(
        values[name] is not None
        for name in ("revenue", "net_income", "operating_cash_flow", "assets", "liabilities")
    )
    if market_cap is not None and available_core >= 4:
        data_quality = "complete"
    elif market_cap is not None and available_core >= 2:
        data_quality = "partial"
    else:
        data_quality = "insufficient"
    filed_dates = sorted(
        {entry["filed"] for entry in selected.values() if entry and entry.get("filed")}
    )
    if any(pd.Timestamp(date) > cutoff for date in filed_dates):
        raise AssertionError("future filing entered point-in-time snapshot")
    latest_annual = selected.get("revenue") or selected.get("net_income")
    return {
        "as_of": cutoff.strftime("%Y-%m-%d"),
        "entity_name": payload.get("entityName"),
        "cik": payload.get("cik"),
        "data_quality": data_quality,
        "latest_annual_period_end": latest_annual.get("end") if latest_annual else None,
        "latest_filed_date": max(filed_dates) if filed_dates else None,
        "filed_dates_used": filed_dates,
        "raw_market_price": raw_market_price,
        "values": values,
        "metrics": metrics,
        "concepts_used": {
            name: entry.get("concept") if entry else None for name, entry in selected.items()
        },
        "source": "SEC EDGAR Company Facts filed-date filtered",
    }


__all__ = [
    "CIK_BY_TICKER",
    "CIK_HISTORY_BY_TICKER",
    "cik_for_ticker",
    "download_companyfacts",
    "fundamental_snapshot",
    "load_companyfacts",
    "sec_user_agent",
]
