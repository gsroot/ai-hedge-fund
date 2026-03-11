"""
financialdatasets.ai REST API 래퍼

Yahoo Finance의 fallback / 보완 데이터소스로 사용합니다.
FINANCIAL_DATASETS_API_KEY 환경변수가 설정된 경우에만 동작합니다.

지원 기능:
- 애널리스트 추정치 (forward EPS/revenue)  → Growth 팩터 강화
- 재무 지표 스냅샷                          → YF 데이터 공백 fallback
"""
import os
import json
import urllib.request
import urllib.error

from cache import _get_cache_path, _read_cache, _write_cache, cache_stats

_API_BASE = "https://api.financialdatasets.ai"
_API_KEY: str | None = None  # 지연 초기화


def _get_api_key() -> str | None:
    global _API_KEY
    if _API_KEY is None:
        _API_KEY = os.environ.get("FINANCIAL_DATASETS_API_KEY", "")
    return _API_KEY or None


def _api_get(path: str, params: dict) -> dict | None:
    """
    financialdatasets.ai API GET 요청.

    API 키 미설정·네트워크 오류 시 None 반환 (예외 전파 없음).
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{_API_BASE}{path}?{query}"

    try:
        req = urllib.request.Request(url, headers={"X-API-KEY": api_key})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


# ============================================================================
# 애널리스트 추정치 (Growth 팩터 보강)
# ============================================================================

def get_analyst_estimates(ticker: str, end_date: str) -> dict | None:
    """
    컨센서스 애널리스트 추정치 조회 (연간, 최신 2기).

    Returns:
        {
            "forward_revenue_growth": float | None,  # 예상 매출 성장률 (YoY)
            "forward_eps_growth":     float | None,  # 예상 EPS 성장률 (YoY)
            "consensus_revenue":      float | None,  # 평균 컨센서스 매출
            "consensus_eps":          float | None,  # 평균 컨센서스 EPS
        }
        FINANCIAL_DATASETS_API_KEY 미설정 또는 데이터 없으면 None.
    """
    if not _get_api_key():
        return None

    cache_path = _get_cache_path("fd_analyst", ticker, end_date, "")
    cached = _read_cache(cache_path)
    if cached is not None:
        cache_stats["hits"] += 1
        return cached

    cache_stats["misses"] += 1
    data = _api_get("/financials/analyst-estimates", {"ticker": ticker, "period": "annual", "limit": "2"})

    if not data or not data.get("analyst_estimates"):
        return None

    estimates = data["analyst_estimates"]
    if not estimates:
        return None

    latest = estimates[0]
    prev = estimates[1] if len(estimates) > 1 else None

    forward_revenue_growth = None
    if prev and prev.get("estimated_revenue_avg") and latest.get("estimated_revenue_avg"):
        prev_rev = prev["estimated_revenue_avg"]
        curr_rev = latest["estimated_revenue_avg"]
        if prev_rev and prev_rev > 0:
            forward_revenue_growth = (curr_rev - prev_rev) / prev_rev

    forward_eps_growth = None
    if prev and prev.get("estimated_eps_avg") and latest.get("estimated_eps_avg"):
        prev_eps = prev["estimated_eps_avg"]
        curr_eps = latest["estimated_eps_avg"]
        if prev_eps and prev_eps > 0:
            forward_eps_growth = (curr_eps - prev_eps) / prev_eps

    result = {
        "forward_revenue_growth": forward_revenue_growth,
        "forward_eps_growth": forward_eps_growth,
        "consensus_revenue": latest.get("estimated_revenue_avg"),
        "consensus_eps": latest.get("estimated_eps_avg"),
    }

    _write_cache(cache_path, result)
    return result


# ============================================================================
# 재무 지표 스냅샷 (YF fallback)
# ============================================================================

def get_metrics_snapshot_fallback(ticker: str, end_date: str) -> dict | None:
    """
    Yahoo Finance 조회 실패 시 재무 지표 스냅샷으로 대체.

    필드 이름을 data_fetcher._fetch_financial_metrics_yf() 반환 형식에 맞춰 정규화합니다.
    FINANCIAL_DATASETS_API_KEY 미설정 또는 데이터 없으면 None.
    """
    if not _get_api_key():
        return None

    cache_path = _get_cache_path("fd_snapshot", ticker, end_date, "")
    cached = _read_cache(cache_path)
    if cached is not None:
        cache_stats["hits"] += 1
        return cached

    cache_stats["misses"] += 1
    data = _api_get("/financial-metrics/snapshot", {"ticker": ticker})

    if not data or not data.get("snapshot"):
        return None

    s = data["snapshot"]
    market_cap = s.get("market_cap")
    free_cash_flow = s.get("free_cash_flow")
    shares = s.get("shares_outstanding")
    total_debt = s.get("total_debt")
    total_cash = s.get("cash_and_equivalents")

    result = {
        "ticker": ticker,
        "company_name": ticker,  # 스냅샷에 회사명 없음 → ticker로 대체

        # 밸류에이션
        "price_to_earnings_ratio": s.get("pe_ratio"),
        "price_to_book_ratio": s.get("price_to_book_ratio"),
        "price_to_sales_ratio": s.get("price_to_sales_ratio"),
        "peg_ratio": s.get("peg_ratio"),
        "enterprise_value_to_ebitda": s.get("ev_to_ebitda"),
        "enterprise_value": s.get("enterprise_value"),
        "enterprise_value_to_revenue": s.get("ev_to_revenue"),

        # 수익성
        "return_on_equity": s.get("return_on_equity"),
        "return_on_assets": s.get("return_on_assets"),
        "return_on_invested_capital": s.get("return_on_invested_capital"),
        "gross_margin": s.get("gross_margin"),
        "operating_margin": s.get("operating_margin"),
        "net_margin": s.get("net_profit_margin"),
        "ebitda": s.get("ebitda"),
        "ebitda_margins": None,

        # 성장
        "revenue_growth": s.get("revenue_growth"),
        "earnings_growth": s.get("earnings_per_share_growth"),
        "earnings_per_share_growth": s.get("earnings_per_share_growth"),

        # 재무 건전성
        "current_ratio": s.get("current_ratio"),
        "quick_ratio": None,
        "debt_to_equity": s.get("debt_to_equity"),
        "interest_coverage": s.get("interest_coverage"),
        "cash_ratio": None,
        "operating_cash_flow_ratio": None,
        "asset_turnover": None,
        "debt_to_assets": (total_debt / (total_debt + market_cap)) if total_debt and market_cap else None,

        # 배당
        "dividend_yield": s.get("dividend_yield"),
        "payout_ratio": s.get("payout_ratio"),

        # 시가총액
        "market_cap": market_cap,
        "shares_outstanding": shares,
        "float_shares": None,

        # 현금흐름
        "free_cash_flow": free_cash_flow,
        "free_cash_flow_yield": (free_cash_flow / market_cap) if free_cash_flow and market_cap else None,
        "free_cash_flow_per_share": (free_cash_flow / shares) if free_cash_flow and shares else None,
        "operating_cashflow": None,

        # 부채/현금
        "total_debt": total_debt,
        "total_cash": total_cash,
        "total_cash_per_share": None,

        # 매출/EPS
        "total_revenue": None,
        "revenue_per_share": s.get("revenue_per_share"),
        "earnings_per_share": s.get("earnings_per_share"),
        "forward_eps": s.get("forward_eps"),
        "book_value_per_share": s.get("book_value_per_share"),

        # 소유권/공매도
        "held_percent_insiders": None,
        "held_percent_institutions": None,
        "short_ratio": None,
        "short_percent_of_float": None,

        # 기술적 지표
        "beta": s.get("beta"),
        "52_week_high": None,
        "52_week_low": None,
        "52_week_change": None,
        "50_day_average": None,
        "200_day_average": None,

        # 섹터/인더스트리
        "sector": None,
        "industry": None,

        # R&D (Fisher 분석용)
        "research_and_development": None,
        "research_and_development_ratio": s.get("research_and_development_ratio"),
    }

    _write_cache(cache_path, result)
    return result
