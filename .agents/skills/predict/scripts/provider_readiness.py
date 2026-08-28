#!/usr/bin/env python3
"""Audit live provider readiness without turning missing evidence into zero.

The output is an evidence snapshot, not a ranking input. Credentials are never
serialized and exception text is scrubbed before it is written.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests
from dotenv import load_dotenv


SCHEMA_VERSION = 1
STATUS_VALUES = {
    "ready",
    "credential_missing",
    "auth_failed",
    "timeout",
    "quota_exceeded",
    "schema_mismatch",
    "empty_sample",
    "stale",
    "unavailable",
}
PROJECT_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(PROJECT_ROOT / ".env", override=False)

PROVIDER_INVENTORY = (
    {
        "provider_id": "dart",
        "market_scope": ["krx"],
        "roles": ["corporate_registry", "financial_statements", "disclosures", "major_shareholders"],
        "credential_env": ["DART_API_KEY"],
        "required_fields": ["status", "corp_name", "stock_code", "corp_cls"],
        "observation_timing": "filing receipt/publication time; amended filings require a separate vintage",
        "revision_policy": "revisions must retain original and amended receipt timestamps",
        "quota": "provider-managed daily quota; status 020 is classified as quota_exceeded",
        "historical_ranking_use": "conditional_on_filing_vintage",
    },
    {
        "provider_id": "krx_open_api",
        "market_scope": ["krx"],
        "roles": ["daily_ohlcv", "market_cap", "listed_shares"],
        "credential_env": ["KRX_API_KEY"],
        "required_fields": ["ISU_CD", "TDD_CLSPRC", "MKTCAP", "LIST_SHRS"],
        "observation_timing": "official daily market row for basDd",
        "revision_policy": "snapshot by requested trade date; corrections are not versioned by this endpoint",
        "quota": "provider-managed; client uses one request per second",
        "historical_ranking_use": "prices_only_after_trade_date_alignment",
    },
    {
        "provider_id": "finance_data_reader",
        "market_scope": ["krx"],
        "roles": ["daily_adjusted_ohlcv", "current_listed_universe"],
        "credential_env": [],
        "required_fields": ["Open", "High", "Low", "Close", "Volume"],
        "observation_timing": "trade-date price rows; current listing is query-time only",
        "revision_policy": "adjusted history may revise and has no explicit vintage identifier",
        "quota": "upstream-dependent and undocumented",
        "historical_ranking_use": "prices_only; current listing is not historical membership",
    },
    {
        "provider_id": "pykrx",
        "market_scope": ["krx"],
        "roles": ["daily_raw_ohlcv", "valuation", "market_cap", "current_index_membership"],
        "credential_env": [],
        "required_fields": ["시가", "고가", "저가", "종가", "거래량"],
        "observation_timing": "trade-date rows; index membership call exposes current/requested provider state",
        "revision_policy": "no explicit vintage identifier for corrections or membership revisions",
        "quota": "upstream-dependent; client throttling required",
        "historical_ranking_use": "prices_and_valuations_only_after_as_of_checks; membership needs archived vintage",
    },
    {
        "provider_id": "naver_news",
        "market_scope": ["krx"],
        "roles": ["current_news_search"],
        "credential_env": ["NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"],
        "required_fields": ["title", "link", "pubDate"],
        "observation_timing": "search result publication time observed at query time",
        "revision_policy": "current search feed; no historical result-set vintage",
        "quota": "provider-managed daily/search quota",
        "historical_ranking_use": "not_allowed_without_archived_point_in_time_corpus",
    },
    {
        "provider_id": "yahoo_chart",
        "market_scope": ["sp500"],
        "roles": ["daily_ohlcv", "current_security_metadata"],
        "credential_env": [],
        "required_fields": ["meta.symbol", "timestamp", "indicators.quote"],
        "observation_timing": "chart timestamps; current metadata is query-time only",
        "revision_policy": "adjusted history may revise; raw download has no explicit vintage identifier",
        "quota": "undocumented public endpoint rate limits",
        "historical_ranking_use": "prices_only; current metadata is not point-in-time evidence",
    },
    {
        "provider_id": "wikipedia_sp500",
        "market_scope": ["sp500"],
        "roles": ["current_constituent_universe"],
        "credential_env": [],
        "required_fields": ["Symbol", "Security", "GICS Sector"],
        "observation_timing": "page state observed at query time",
        "revision_policy": "page history must be captured separately for historical membership",
        "quota": "public page; no service guarantee",
        "historical_ranking_use": "current_universe_only; never backfill prior periods",
    },
)


def classify_http_status(status_code: int) -> str:
    if status_code in {401, 403}:
        return "auth_failed"
    if status_code == 408:
        return "timeout"
    if status_code == 429:
        return "quota_exceeded"
    if status_code >= 400:
        return "unavailable"
    return "ready"


def missing_credentials(names: list[str], environ: dict[str, str] | None = None) -> list[str]:
    source = os.environ if environ is None else environ
    return [name for name in names if not source.get(name)]


def assess_sample(
    payload: dict[str, Any] | None,
    *,
    required_fields: list[str],
    rows: int | None = None,
) -> tuple[str, list[str]]:
    if rows == 0:
        return "empty_sample", list(required_fields)
    if not isinstance(payload, dict):
        return "schema_mismatch", list(required_fields)
    missing = [field for field in required_fields if not _has_path(payload, field)]
    return ("schema_mismatch" if missing else "ready"), missing


def apply_staleness(
    result: dict[str, Any],
    *,
    requested_as_of: str,
    max_lag_days: int = 7,
) -> dict[str, Any]:
    if result.get("status") != "ready" or not result.get("data_as_of"):
        return result
    raw = str(result["data_as_of"])
    try:
        observed = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            observed = parsedate_to_datetime(raw).date()
        except (TypeError, ValueError):
            result["status"] = "schema_mismatch"
            result["error"] = {"kind": "schema_mismatch", "message": "unparseable data_as_of"}
            return result
    requested = datetime.strptime(requested_as_of, "%Y-%m-%d").date()
    lag_days = (requested - observed).days
    if lag_days > max_lag_days:
        result["status"] = "stale"
        result["error"] = {"kind": "stale", "lag_days": lag_days, "max_lag_days": max_lag_days}
    return result


def _has_path(payload: dict[str, Any], dotted: str) -> bool:
    value: Any = payload
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    return value is not None


def _scrub_error(error: BaseException) -> str:
    message = f"{type(error).__name__}: {error}"
    for name in ("DART_API_KEY", "KRX_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"):
        secret = os.environ.get(name)
        if secret:
            message = message.replace(secret, f"<{name}:redacted>")
    return message[:500]


def _base_result(provider: dict[str, Any]) -> dict[str, Any]:
    credential_names = list(provider["credential_env"])
    missing = missing_credentials(credential_names)
    return {
        "provider_id": provider["provider_id"],
        "market_scope": provider["market_scope"],
        "roles": provider["roles"],
        "credential_requirements": credential_names,
        "credentials_configured": not missing,
        "missing_credentials": missing,
        "required_fields": provider["required_fields"],
        "observation_timing": provider["observation_timing"],
        "revision_policy": provider["revision_policy"],
        "quota": provider["quota"],
        "historical_ranking_use": provider["historical_ranking_use"],
        "observed_at": datetime.now(UTC).isoformat(),
        "data_as_of": None,
        "sample_size": 0,
        "status": "credential_missing" if missing else "unavailable",
        "missing_fields": [],
        "error": None,
        "ranking_evidence_value": "missing_evidence_not_numeric_zero",
    }


def _request_json(
    result: dict[str, Any],
    request: Callable[[], requests.Response],
) -> dict[str, Any] | None:
    try:
        response = request()
        status = classify_http_status(response.status_code)
        if status != "ready":
            result["status"] = status
            result["error"] = {"kind": status, "http_status": response.status_code}
            return None
        try:
            return response.json()
        except ValueError as error:
            result["status"] = "schema_mismatch"
            result["error"] = {"kind": "schema_mismatch", "message": _scrub_error(error)}
            return None
    except requests.Timeout as error:
        result["status"] = "timeout"
        result["error"] = {"kind": "timeout", "message": _scrub_error(error)}
    except requests.RequestException as error:
        result["status"] = "unavailable"
        result["error"] = {"kind": "unavailable", "message": _scrub_error(error)}
    return None


def _check_dart(provider: dict[str, Any], _as_of: str) -> dict[str, Any]:
    result = _base_result(provider)
    if result["missing_credentials"]:
        return result
    payload = _request_json(
        result,
        lambda: requests.get(
            "https://opendart.fss.or.kr/api/company.json",
            params={"crtfc_key": os.environ["DART_API_KEY"], "corp_code": "00126380"},
            timeout=10,
        ),
    )
    if payload is None:
        return result
    dart_status = str(payload.get("status", ""))
    if dart_status != "000":
        kind = {"010": "credential_missing", "011": "auth_failed", "020": "quota_exceeded", "901": "auth_failed"}.get(
            dart_status, "unavailable"
        )
        result["status"] = kind
        result["error"] = {"kind": kind, "provider_status": dart_status, "message": payload.get("message")}
        return result
    status, missing = assess_sample(payload, required_fields=provider["required_fields"], rows=1)
    result.update(status=status, missing_fields=missing, sample_size=1, data_as_of=result["observed_at"])
    return result


def _check_krx(provider: dict[str, Any], as_of: str) -> dict[str, Any]:
    result = _base_result(provider)
    if result["missing_credentials"]:
        return result
    payload = _request_json(
        result,
        lambda: requests.get(
            "http://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd",
            params={"AUTH_KEY": os.environ["KRX_API_KEY"], "basDd": as_of.replace("-", "")},
            timeout=10,
        ),
    )
    if payload is None:
        return result
    rows = payload.get("OutBlock_1")
    first = rows[0] if isinstance(rows, list) and rows else None
    status, missing = assess_sample(first, required_fields=provider["required_fields"], rows=len(rows or []))
    result.update(status=status, missing_fields=missing, sample_size=len(rows or []), data_as_of=as_of)
    return result


def _check_naver(provider: dict[str, Any], _as_of: str) -> dict[str, Any]:
    result = _base_result(provider)
    if result["missing_credentials"]:
        return result
    payload = _request_json(
        result,
        lambda: requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            params={"query": "삼성전자", "display": 1, "sort": "date"},
            headers={
                "X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
                "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"],
            },
            timeout=10,
        ),
    )
    if payload is None:
        return result
    rows = payload.get("items")
    first = rows[0] if isinstance(rows, list) and rows else None
    status, missing = assess_sample(first, required_fields=provider["required_fields"], rows=len(rows or []))
    result.update(
        status=status,
        missing_fields=missing,
        sample_size=len(rows or []),
        data_as_of=(first or {}).get("pubDate"),
    )
    return result


def _check_finance_data_reader(provider: dict[str, Any], as_of: str) -> dict[str, Any]:
    result = _base_result(provider)
    try:
        import FinanceDataReader as fdr

        end = datetime.strptime(as_of, "%Y-%m-%d") + timedelta(days=1)
        start = end - timedelta(days=15)
        frame = fdr.DataReader("005930", start.date().isoformat(), end.date().isoformat())
        missing = [field for field in provider["required_fields"] if field not in frame.columns]
        result.update(
            status=("empty_sample" if frame.empty else "schema_mismatch" if missing else "ready"),
            missing_fields=missing,
            sample_size=len(frame.index),
            data_as_of=(frame.index.max().date().isoformat() if not frame.empty else None),
        )
    except Exception as error:
        result["status"] = "unavailable"
        result["error"] = {"kind": "unavailable", "message": _scrub_error(error)}
    return result


def _check_pykrx(provider: dict[str, Any], as_of: str) -> dict[str, Any]:
    result = _base_result(provider)
    try:
        from pykrx import stock

        end = datetime.strptime(as_of, "%Y-%m-%d")
        start = end - timedelta(days=15)
        frame = stock.get_market_ohlcv_by_date(
            start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), "005930", adjusted=False
        )
        missing = [field for field in provider["required_fields"] if field not in frame.columns]
        result.update(
            status=("empty_sample" if frame.empty else "schema_mismatch" if missing else "ready"),
            missing_fields=missing,
            sample_size=len(frame.index),
            data_as_of=(frame.index.max().date().isoformat() if not frame.empty else None),
        )
    except Exception as error:
        result["status"] = "unavailable"
        result["error"] = {"kind": "unavailable", "message": _scrub_error(error)}
    return result


def _check_yahoo(provider: dict[str, Any], as_of: str) -> dict[str, Any]:
    result = _base_result(provider)
    end = datetime.strptime(as_of, "%Y-%m-%d").replace(tzinfo=UTC) + timedelta(days=1)
    start = end - timedelta(days=15)
    payload = _request_json(
        result,
        lambda: requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
            params={"period1": int(start.timestamp()), "period2": int(end.timestamp()), "interval": "1d"},
            headers={"User-Agent": "Mozilla/5.0 AgentOSProviderReadiness/1.0"},
            timeout=10,
        ),
    )
    if payload is None:
        return result
    chart = payload.get("chart") if isinstance(payload, dict) else None
    rows = chart.get("result") if isinstance(chart, dict) else None
    first = rows[0] if isinstance(rows, list) and rows else None
    status, missing = assess_sample(first, required_fields=provider["required_fields"], rows=len(rows or []))
    timestamps = (first or {}).get("timestamp") or []
    result.update(
        status=status,
        missing_fields=missing,
        sample_size=len(timestamps),
        data_as_of=(datetime.fromtimestamp(max(timestamps), UTC).date().isoformat() if timestamps else None),
    )
    return result


def _check_wikipedia(provider: dict[str, Any], _as_of: str) -> dict[str, Any]:
    result = _base_result(provider)
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        table = tables[0] if tables else pd.DataFrame()
        missing = [field for field in provider["required_fields"] if field not in table.columns]
        result.update(
            status=("empty_sample" if table.empty else "schema_mismatch" if missing else "ready"),
            missing_fields=missing,
            sample_size=len(table.index),
            data_as_of=result["observed_at"],
        )
    except Exception as error:
        result["status"] = "unavailable"
        result["error"] = {"kind": "unavailable", "message": _scrub_error(error)}
    return result


CHECKS: dict[str, Callable[[dict[str, Any], str], dict[str, Any]]] = {
    "dart": _check_dart,
    "krx_open_api": _check_krx,
    "finance_data_reader": _check_finance_data_reader,
    "pykrx": _check_pykrx,
    "naver_news": _check_naver,
    "yahoo_chart": _check_yahoo,
    "wikipedia_sp500": _check_wikipedia,
}


def run_checks(as_of: str) -> dict[str, Any]:
    samples = [
        apply_staleness(CHECKS[provider["provider_id"]](provider, as_of), requested_as_of=as_of)
        for provider in PROVIDER_INVENTORY
    ]
    assert all(item["status"] in STATUS_VALUES for item in samples)
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_id": "provider_readiness_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "requested_as_of": as_of,
        "ranking_policy": "fail_closed_missing_evidence_not_zero",
        "inventory": list(PROVIDER_INVENTORY),
        "samples": samples,
        "summary": {
            "ready": sum(item["status"] == "ready" for item in samples),
            "not_ready": sum(item["status"] != "ready" for item in samples),
            "all_required_ready": all(item["status"] == "ready" for item in samples),
        },
    }


def build_provider_readiness_policy(
    payload: dict[str, Any] | None,
    *,
    market_scope: str,
    analysis_date: str,
    source: str | None = None,
) -> dict[str, Any]:
    """Validate and narrow a readiness snapshot for a predict run."""
    if payload is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "contract_id": "provider_readiness_v1",
            "mode": "not_provided",
            "source": None,
            "market_scope": market_scope,
            "analysis_date": analysis_date,
            "all_samples_ready": False,
            "provider_status": {},
            "ranking_policy": "missing_evidence_requires_prior_or_explanation_only",
        }
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"provider readiness schema_version must be {SCHEMA_VERSION}")
    if payload.get("contract_id") != "provider_readiness_v1":
        raise ValueError("provider readiness contract_id must be provider_readiness_v1")
    requested_as_of = str(payload.get("requested_as_of") or "")
    try:
        requested_date = datetime.strptime(requested_as_of, "%Y-%m-%d").date()
        run_date = datetime.strptime(analysis_date, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError("provider readiness dates must use YYYY-MM-DD") from error
    if requested_date > run_date:
        raise ValueError("provider readiness requested_as_of cannot exceed analysis_date")
    samples = payload.get("samples")
    if not isinstance(samples, list):
        raise ValueError("provider readiness samples must be a list")
    applicable = [
        sample
        for sample in samples
        if isinstance(sample, dict) and market_scope in (sample.get("market_scope") or [])
    ]
    if not applicable:
        raise ValueError(f"provider readiness has no samples for {market_scope}")
    provider_status = {
        str(sample.get("provider_id")): {
            "status": sample.get("status"),
            "data_as_of": sample.get("data_as_of"),
            "sample_size": sample.get("sample_size"),
            "historical_ranking_use": sample.get("historical_ranking_use"),
            "ranking_evidence_value": sample.get("ranking_evidence_value"),
        }
        for sample in applicable
    }
    invalid_statuses = sorted(
        {
            str(item["status"])
            for item in provider_status.values()
            if item["status"] not in STATUS_VALUES
        }
    )
    if invalid_statuses:
        raise ValueError(f"provider readiness has invalid statuses: {invalid_statuses}")
    all_ready = all(item["status"] == "ready" for item in provider_status.values())
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_id": "provider_readiness_v1",
        "mode": "sampled",
        "source": source,
        "market_scope": market_scope,
        "analysis_date": analysis_date,
        "requested_as_of": requested_as_of,
        "all_samples_ready": all_ready,
        "provider_status": provider_status,
        "ranking_policy": (
            "provider_ready_but_point_in_time_contract_still_required"
            if all_ready
            else "missing_evidence_requires_prior_or_explanation_only"
        ),
    }


def load_provider_readiness_policy(
    path: str | Path | None,
    *,
    market_scope: str,
    analysis_date: str,
) -> dict[str, Any]:
    if path is None:
        return build_provider_readiness_policy(
            None, market_scope=market_scope, analysis_date=analysis_date
        )
    source_path = Path(path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("provider readiness JSON must be an object")
    return build_provider_readiness_policy(
        payload,
        market_scope=market_scope,
        analysis_date=analysis_date,
        source=str(source_path.resolve()),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="Sample data date in YYYY-MM-DD")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    datetime.strptime(args.as_of, "%Y-%m-%d")
    payload = run_checks(args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    for sample in payload["samples"]:
        print(f"{sample['provider_id']}: {sample['status']} ({sample['sample_size']} rows)")


if __name__ == "__main__":
    main()
