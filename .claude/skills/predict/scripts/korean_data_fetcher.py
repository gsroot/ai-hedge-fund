"""
한국 주식 데이터 페처 (KRX Open API + FinanceDataReader + PyKRX + DART API)

데이터 소스별 역할 (3단계 폴백):
- KRX Open API (data-dbg.krx.co.kr): 시가총액, 종목리스트 — KRX_API_KEY 설정 시 활성화
- FinanceDataReader (FDR): 가격(OHLCV, 수정주가), 종목리스트 — 가격 primary
- PyKRX: 가격(OHLCV, 미보정), PER/PBR/EPS/BPS/DIV, 시가총액 — 최종 fallback
- DART API (OpenDartReader): 재무제표, 공시, 주요주주 — 유일한 소스

폴백 체인 (KRX_API_KEY 설정 시):
  OHLCV 가격:  FDR(수정주가) → PyKRX
  PER/PBR/EPS: PyKRX (KRX REST API 미제공)
  시가총액:     KRX API → PyKRX
  종목리스트:   FDR → KRX API → PyKRX
  재무제표:     DART (유일, 변경 없음)

KRX REST API 제약사항:
  - 단일 날짜 전체 종목 조회만 지원 (날짜 범위/종목 필터링 불가)
  - PER/PBR/EPS 미제공 (OHLCV + MKTCAP + 상장주식수만 제공)
  - KRX_API_KEY 미설정 시 KRX API 단계 자동 스킵

기존 yfinance data_fetcher와 동일한 dict 형식을 반환하여 호환성을 보장합니다.
"""
import os
import time
import threading
from collections import deque
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

from dotenv import load_dotenv
load_dotenv()


# ============================================================================
# DART Rate Limiter (슬라이딩 윈도우, thread-safe)
# ============================================================================

_dart_request_times = deque()
_dart_lock = threading.Lock()

# 설정값 (config.py에서도 정의하지만, 여기서 독립적으로도 동작하도록 기본값 설정)
DART_RATE_LIMIT = 100  # 분당 최대 요청 수
DART_RATE_WINDOW = 60  # 윈도우 크기 (초)


def _dart_rate_limit():
    """DART API 슬라이딩 윈도우 rate limiter"""
    with _dart_lock:
        now = time.time()
        # 윈도우 밖의 오래된 요청 타임스탬프 제거
        while _dart_request_times and _dart_request_times[0] < now - DART_RATE_WINDOW:
            _dart_request_times.popleft()

        # 윈도우 내 요청 수가 제한에 도달하면 대기
        if len(_dart_request_times) >= DART_RATE_LIMIT:
            sleep_until = _dart_request_times[0] + DART_RATE_WINDOW
            sleep_time = sleep_until - now
            if sleep_time > 0:
                time.sleep(sleep_time)

        _dart_request_times.append(time.time())


# ============================================================================
# KRX Open API (data-dbg.krx.co.kr) — REST API
# ============================================================================
#
# KRX REST API 제약사항:
#   - 단일 날짜 전체 종목 조회만 지원 (날짜 범위/종목 필터링 불가)
#   - PER/PBR/EPS 미제공 (OHLCV + MKTCAP + 상장주식수만 제공)
#   - 엔드포인트: stk_bydd_trd (KOSPI), ksq_bydd_trd (KOSDAQ)

_KRX_API_BASE = "http://data-dbg.krx.co.kr/svc/apis"

# KRX Rate Limiter (경험적 ~1초/요청)
_krx_last_request_time = 0.0
_krx_lock = threading.Lock()
KRX_RATE_LIMIT_DELAY = 1.0  # KRX API 요청 간 딜레이 (초)

# KRX API 응답 캐시 (단일 날짜 전체 종목 — 같은 날짜 반복 요청 방지)
_krx_cache = {}  # {(market, date_str): [items]}
_KRX_CACHE_MAX = 10  # 최대 캐시 항목 수


def _krx_rate_limit():
    """KRX API 요청 간 최소 딜레이 보장"""
    global _krx_last_request_time
    with _krx_lock:
        now = time.time()
        elapsed = now - _krx_last_request_time
        if elapsed < KRX_RATE_LIMIT_DELAY:
            time.sleep(KRX_RATE_LIMIT_DELAY - elapsed)
        _krx_last_request_time = time.time()


def _krx_api_available() -> bool:
    """KRX API 키가 설정되어 있는지 확인"""
    return bool(os.environ.get("KRX_API_KEY"))


def _krx_fetch_market_data(market: str, date_str: str) -> list:
    """
    KRX REST API에서 특정 날짜의 전체 종목 데이터 조회

    단일 호출로 해당 시장의 전체 종목 OHLCV + MKTCAP을 반환합니다.
    동일 (market, date) 요청은 메모리 캐시로 재사용합니다.

    Args:
        market: "KOSPI" 또는 "KOSDAQ"
        date_str: 날짜 (YYYYMMDD)

    Returns:
        list[dict]: KRX API OutBlock_1 항목 리스트
        각 항목: ISU_CD, ISU_NM, TDD_CLSPRC, TDD_OPNPRC, TDD_HGPRC,
                 TDD_LWPRC, ACC_TRDVOL, MKTCAP, LIST_SHRS 등
    """
    cache_key = (market.upper(), date_str)

    # 캐시 확인
    if cache_key in _krx_cache:
        return _krx_cache[cache_key]

    # 시장별 엔드포인트
    market_upper = market.upper()
    if market_upper in ("KOSDAQ", "KOSDAQ150"):
        endpoint = "ksq_bydd_trd"
    else:
        endpoint = "stk_bydd_trd"

    auth_key = os.environ.get("KRX_API_KEY", "")
    url = f"{_KRX_API_BASE}/sto/{endpoint}"
    params = {
        "AUTH_KEY": auth_key,
        "basDd": date_str,
    }

    _krx_rate_limit()
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()

    data = resp.json()
    items = data.get("OutBlock_1", [])

    # 캐시 저장 (크기 제한)
    if len(_krx_cache) >= _KRX_CACHE_MAX:
        # 가장 오래된 항목 제거
        oldest_key = next(iter(_krx_cache))
        del _krx_cache[oldest_key]
    _krx_cache[cache_key] = items

    return items


def _krx_find_stock(ticker: str, date_str: str) -> Optional[dict]:
    """
    KRX API에서 특정 종목 데이터 검색

    전체 종목 데이터를 조회한 후 종목코드로 필터링합니다.
    KOSPI → KOSDAQ 순으로 검색합니다.

    Args:
        ticker: 6자리 종목코드
        date_str: 날짜 (YYYYMMDD)

    Returns:
        KRX 종목 데이터 dict 또는 None
    """
    for market in ["KOSPI", "KOSDAQ"]:
        items = _krx_fetch_market_data(market, date_str)
        for item in items:
            if item.get("ISU_CD") == ticker:
                return item
    return None


def _market_cap_from_krx(ticker: str, end_date: str) -> Optional[float]:
    """
    KRX REST API에서 시가총액 조회

    해당 날짜에 데이터가 없으면 최근 7일까지 역순 탐색합니다.

    Args:
        ticker: 6자리 종목코드
        end_date: 기준 날짜 (YYYY-MM-DD)

    Returns:
        시가총액 (원) 또는 None
    """
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    # 기준일부터 최대 7일 전까지 역순 탐색 (휴장일 대응)
    for days_back in range(8):
        date = end_dt - timedelta(days=days_back)
        date_str = date.strftime("%Y%m%d")
        item = _krx_find_stock(ticker, date_str)
        if item is not None:
            mktcap = item.get("MKTCAP")
            if mktcap is not None:
                try:
                    cap_f = float(str(mktcap).replace(",", "").strip())
                    if cap_f > 0:
                        return cap_f
                except (ValueError, TypeError):
                    pass
            return None  # 종목은 찾았으나 시총 데이터 없음
    return None


def _tickers_from_krx(market: str) -> list:
    """
    KRX REST API에서 종목리스트 가져오기

    전체 종목 일별시세에서 ISU_CD(종목코드) 추출.
    오늘 날짜에 데이터가 없으면 최근 7일까지 역순 탐색합니다.

    Args:
        market: "KOSPI", "KOSDAQ" 등

    Returns:
        list[str]: 6자리 종목코드 리스트
    """
    # KOSPI200/KOSDAQ150은 KRX 전체시세 API로 구분 불가 → 건너뜀 (PyKRX 인덱스 조회로 폴백)
    if market.upper() in ("KOSPI200", "KOSDAQ150"):
        return []

    # 오늘부터 최대 7일 전까지 역순 탐색 (휴장일/미래 날짜 대응)
    for days_back in range(8):
        date = datetime.now() - timedelta(days=days_back)
        date_str = date.strftime("%Y%m%d")
        items = _krx_fetch_market_data(market, date_str)
        if items:
            tickers = []
            for item in items:
                code = str(item.get("ISU_CD", "")).strip()
                if len(code) == 6 and code.isdigit():
                    tickers.append(code)
            if tickers:
                return tickers
    return []


def _get_dart_reader():
    """OpenDartReader 인스턴스 생성 (lazy import)"""
    try:
        import OpenDartReader
    except ImportError:
        raise ImportError("OpenDartReader가 설치되지 않았습니다. 설치: pip install opendartreader")

    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        raise ValueError("DART_API_KEY 환경변수가 설정되지 않았습니다. .env 파일에 DART_API_KEY를 추가하세요.")

    # OpenDartReader 패키지는 import 시 클래스 자체를 반환
    if callable(OpenDartReader):
        return OpenDartReader(api_key)
    return OpenDartReader.OpenDartReader(api_key)


def _get_fdr():
    """FinanceDataReader lazy import"""
    try:
        import FinanceDataReader as fdr
        return fdr
    except ImportError:
        raise ImportError("FinanceDataReader가 설치되지 않았습니다. 설치: pip install finance-datareader")


def _get_pykrx():
    """pykrx 모듈 lazy import"""
    try:
        from pykrx import stock as pykrx_stock
        return pykrx_stock
    except ImportError:
        raise ImportError("pykrx가 설치되지 않았습니다. 설치: pip install pykrx")


def _fetch_with_chain(sources: list, label: str = ""):
    """
    여러 데이터 소스를 순차 시도하는 폴백 체인.

    Args:
        sources: [(name, callable), ...] — 이름과 호출 함수 쌍 리스트
        label: 로깅용 라벨

    Returns:
        첫 번째 성공한 소스의 결과. 모두 실패하면 None.
    """
    for i, (name, fn) in enumerate(sources):
        try:
            result = fn()
            if result is not None and (not hasattr(result, '__len__') or len(result) > 0):
                return result
        except Exception as e:
            is_last = (i == len(sources) - 1)
            if is_last:
                print(f"   ⚠️ {label} 모든 소스 실패 (마지막: {name}): {e}")
            else:
                print(f"   ⚠️ {label} {name} 실패: {e}")
    return None


def _fetch_with_fallback(primary_fn, fallback_fn, label=""):
    """
    primary 소스 실패 시 fallback 소스로 자동 전환.
    (하위 호환 — 내부적으로 _fetch_with_chain() 사용)

    Args:
        primary_fn: primary 데이터 소스 호출 함수 (callable, no args)
        fallback_fn: fallback 데이터 소스 호출 함수
        label: 로깅용 라벨

    Returns:
        primary 또는 fallback 결과. 둘 다 실패하면 None.
    """
    return _fetch_with_chain(
        sources=[("primary", primary_fn), ("fallback", fallback_fn)],
        label=label,
    )


# ============================================================================
# DART 재무제표 한국어 계정 매핑
# ============================================================================

# 계정과목 키워드 매핑 (복수 키워드로 기업 간 용어 차이 대응)
ACCOUNT_MAPPING = {
    "revenue": ["매출액", "수익(매출액)", "영업수익", "매출"],
    "gross_profit": ["매출총이익"],
    "operating_income": ["영업이익", "영업이익(손실)"],
    "net_income": ["당기순이익", "당기순이익(손실)", "분기순이익"],
    "total_assets": ["자산총계"],
    "total_liabilities": ["부채총계"],
    "shareholders_equity": ["자본총계"],
    "current_assets": ["유동자산"],
    "current_liabilities": ["유동부채"],
    "capital_expenditure": ["유형자산의 취득"],
    "depreciation_and_amortization": ["감가상각비", "유무형자산상각비"],
    "research_and_development": ["연구개발비", "경상연구개발비"],
    "interest_expense": ["이자비용"],
    "dividends": ["배당금지급", "배당금의 지급"],
    "share_buybacks": ["자기주식의 취득", "자기주식의 처분"],
}


def _find_account_value(df: pd.DataFrame, account_keywords: list, amount_col: str = "thstrm_amount") -> Optional[float]:
    """
    DART 재무제표 DataFrame에서 계정과목 키워드로 금액 검색

    Args:
        df: DART finstate() 반환 DataFrame
        account_keywords: 검색할 계정과목 키워드 리스트
        amount_col: 금액 컬럼명 (thstrm_amount=당기, frmtrm_amount=전기)

    Returns:
        매칭된 계정과목의 금액 (float) 또는 None
    """
    if df is None or df.empty:
        return None

    if "account_nm" not in df.columns or amount_col not in df.columns:
        return None

    for keyword in account_keywords:
        matches = df[df["account_nm"].str.contains(keyword, na=False)]
        if not matches.empty:
            # 연결재무제표(CFS) 우선, 없으면 개별재무제표(OFS)
            for fs_div in ["CFS", "OFS"]:
                if "fs_div" in matches.columns:
                    div_matches = matches[matches["fs_div"] == fs_div]
                    if not div_matches.empty:
                        val = div_matches.iloc[0][amount_col]
                        try:
                            return float(str(val).replace(",", ""))
                        except (ValueError, TypeError):
                            continue

            # fs_div 컬럼이 없는 경우 첫 번째 매칭 사용
            val = matches.iloc[0][amount_col]
            try:
                return float(str(val).replace(",", ""))
            except (ValueError, TypeError):
                pass

    return None


# ============================================================================
# DART 재무제표 기반 파생 지표 계산
# ============================================================================

def _derive_metrics_from_dart(ticker: str, end_date: str) -> dict:
    """
    DART 재무제표에서 파생 지표 계산

    Args:
        ticker: 6자리 한국 종목코드
        end_date: 기준 날짜 (YYYY-MM-DD)

    Returns:
        dict: 마진, ROE, 성장률 등 파생 지표
    """
    KR_CORPORATE_TAX_RATE = 0.22

    derived = {
        "gross_margin": None,
        "operating_margin": None,
        "net_margin": None,
        "return_on_equity": None,
        "return_on_assets": None,
        "return_on_invested_capital": None,
        "debt_to_equity": None,
        "current_ratio": None,
        "interest_coverage": None,
        "asset_turnover": None,
        "revenue_growth": None,
        "earnings_growth": None,
        "research_and_development": None,
        "research_and_development_ratio": None,
    }

    try:
        dart = _get_dart_reader()
        _dart_rate_limit()

        # 기준 연도 결정
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        year = end_dt.year
        # 1분기(~3월)인 경우 전년도 사업보고서 사용
        if end_dt.month <= 3:
            year -= 1

        # 사업보고서 조회 (연간)
        df = dart.finstate(ticker, year)

        if df is None or df.empty:
            # 전년도 시도
            df = dart.finstate(ticker, year - 1)
            if df is None or df.empty:
                return derived

        # 당기 금액 추출
        revenue = _find_account_value(df, ACCOUNT_MAPPING["revenue"], "thstrm_amount")
        gross_profit = _find_account_value(df, ACCOUNT_MAPPING["gross_profit"], "thstrm_amount")
        operating_income = _find_account_value(df, ACCOUNT_MAPPING["operating_income"], "thstrm_amount")
        net_income = _find_account_value(df, ACCOUNT_MAPPING["net_income"], "thstrm_amount")
        total_assets = _find_account_value(df, ACCOUNT_MAPPING["total_assets"], "thstrm_amount")
        total_liabilities = _find_account_value(df, ACCOUNT_MAPPING["total_liabilities"], "thstrm_amount")
        total_equity = _find_account_value(df, ACCOUNT_MAPPING["shareholders_equity"], "thstrm_amount")
        current_assets = _find_account_value(df, ACCOUNT_MAPPING["current_assets"], "thstrm_amount")
        current_liabilities = _find_account_value(df, ACCOUNT_MAPPING["current_liabilities"], "thstrm_amount")
        interest_expense = _find_account_value(df, ACCOUNT_MAPPING["interest_expense"], "thstrm_amount")
        rd_value = _find_account_value(df, ACCOUNT_MAPPING["research_and_development"], "thstrm_amount")

        # 전기 금액 (성장률 계산용)
        prev_revenue = _find_account_value(df, ACCOUNT_MAPPING["revenue"], "frmtrm_amount")
        prev_net_income = _find_account_value(df, ACCOUNT_MAPPING["net_income"], "frmtrm_amount")

        # 마진 계산
        if revenue and revenue != 0:
            if gross_profit is not None:
                derived["gross_margin"] = gross_profit / revenue
            if operating_income is not None:
                derived["operating_margin"] = operating_income / revenue
            if net_income is not None:
                derived["net_margin"] = net_income / revenue

        # ROE, ROA
        if net_income is not None:
            if total_equity and total_equity != 0:
                derived["return_on_equity"] = net_income / total_equity
            if total_assets and total_assets != 0:
                derived["return_on_assets"] = net_income / total_assets

        # ROIC = NOPAT / (Total Assets - Current Liabilities)
        if operating_income is not None and total_assets and current_liabilities is not None:
            nopat = operating_income * (1 - KR_CORPORATE_TAX_RATE)
            invested_capital = total_assets - current_liabilities
            if invested_capital > 0:
                derived["return_on_invested_capital"] = nopat / invested_capital

        # Debt/Equity
        if total_liabilities is not None and total_equity and total_equity != 0:
            derived["debt_to_equity"] = total_liabilities / total_equity

        # Current Ratio
        if current_assets is not None and current_liabilities and current_liabilities != 0:
            derived["current_ratio"] = current_assets / current_liabilities

        # Interest Coverage
        if operating_income is not None and interest_expense and abs(interest_expense) > 0:
            derived["interest_coverage"] = operating_income / abs(interest_expense)

        # Asset Turnover
        if revenue and total_assets and total_assets != 0:
            derived["asset_turnover"] = revenue / total_assets

        # Revenue Growth
        if revenue is not None and prev_revenue and abs(prev_revenue) > 0:
            derived["revenue_growth"] = (revenue - prev_revenue) / abs(prev_revenue)

        # Earnings Growth
        if net_income is not None and prev_net_income and abs(prev_net_income) > 0:
            derived["earnings_growth"] = (net_income - prev_net_income) / abs(prev_net_income)

        # R&D
        if rd_value and rd_value > 0:
            derived["research_and_development"] = rd_value
            if revenue and revenue > 0:
                derived["research_and_development_ratio"] = rd_value / revenue

    except Exception as e:
        print(f"   ⚠️ DART 재무제표 파생 지표 계산 실패 ({ticker}): {e}")

    return derived


# ============================================================================
# PyKRX 기본 지표 (PER, PBR, EPS, 시총 등)
# ============================================================================

def _get_pykrx_fundamental_raw(ticker: str, end_date: str) -> dict:
    """
    PyKRX에서 기본 밸류에이션 지표 가져오기 (내부 구현)

    Args:
        ticker: 6자리 종목코드
        end_date: 기준 날짜 (YYYY-MM-DD)

    Returns:
        dict: PER, PBR, EPS, BPS, DIV, market_cap
    """
    result = {
        "price_to_earnings_ratio": None,
        "price_to_book_ratio": None,
        "earnings_per_share": None,
        "book_value_per_share": None,
        "dividend_yield": None,
        "market_cap": None,
    }

    pykrx = _get_pykrx()
    date_str = end_date.replace("-", "")

    # 기본 지표 (PER, PBR, EPS, BPS, DIV)
    df_fundamental = pykrx.get_market_fundamental(date_str, date_str, ticker)

    if df_fundamental is not None and not df_fundamental.empty:
        row = df_fundamental.iloc[0]
        per = row.get("PER", None)
        pbr = row.get("PBR", None)
        eps = row.get("EPS", None)
        bps = row.get("BPS", None)
        div_yield = row.get("DIV", None)

        if per and per > 0:
            result["price_to_earnings_ratio"] = float(per)
        if pbr and pbr > 0:
            result["price_to_book_ratio"] = float(pbr)
        if eps and eps != 0:
            result["earnings_per_share"] = float(eps)
        if bps and bps > 0:
            result["book_value_per_share"] = float(bps)
        if div_yield is not None:
            result["dividend_yield"] = float(div_yield) / 100.0  # % → 소수

    # 시가총액
    df_cap = pykrx.get_market_cap(date_str, date_str, ticker)
    if df_cap is not None and not df_cap.empty:
        cap_row = df_cap.iloc[0]
        market_cap = cap_row.get("시가총액", None)
        if market_cap and market_cap > 0:
            result["market_cap"] = float(market_cap)

    return result


def _get_pykrx_fundamental(ticker: str, end_date: str) -> dict:
    """
    기본 밸류에이션 지표 가져오기 (PyKRX)

    KRX REST API는 PER/PBR/EPS를 제공하지 않으므로 PyKRX만 사용합니다.
    시가총액은 KRX API가 제공하므로 get_market_cap_kr()에서 별도 체인으로 처리합니다.

    Args:
        ticker: 6자리 종목코드
        end_date: 기준 날짜 (YYYY-MM-DD)

    Returns:
        dict: PER, PBR, EPS, BPS, DIV, market_cap
    """
    try:
        return _get_pykrx_fundamental_raw(ticker, end_date)
    except Exception as e:
        print(f"   ⚠️ PyKRX 기본 지표 조회 실패 ({ticker}): {e}")
        return {
            "price_to_earnings_ratio": None,
            "price_to_book_ratio": None,
            "earnings_per_share": None,
            "book_value_per_share": None,
            "dividend_yield": None,
            "market_cap": None,
        }


# ============================================================================
# 공개 함수: 재무 지표
# ============================================================================

def get_financial_metrics_kr(ticker: str, end_date: str) -> dict:
    """
    한국 주식 재무 지표 수집 (PyKRX + DART)

    yfinance data_fetcher의 _fetch_financial_metrics_yf()와 동일한 dict 형식 반환.

    Args:
        ticker: 6자리 종목코드
        end_date: 기준 날짜 (YYYY-MM-DD)

    Returns:
        dict: yfinance info 호환 형식의 재무 지표
    """
    # PyKRX 기본 지표
    pykrx_data = _get_pykrx_fundamental(ticker, end_date)

    # DART 파생 지표
    dart_data = _derive_metrics_from_dart(ticker, end_date)

    market_cap = pykrx_data.get("market_cap")

    return {
        "ticker": ticker,
        "company_name": _get_company_name(ticker),
        "report_period": end_date,

        # ===== 밸류에이션 지표 (PyKRX) =====
        "price_to_earnings_ratio": pykrx_data.get("price_to_earnings_ratio"),
        "price_to_book_ratio": pykrx_data.get("price_to_book_ratio"),
        "price_to_sales_ratio": None,  # PyKRX에서 직접 제공하지 않음
        "peg_ratio": None,  # 한국 데이터소스에서 미제공
        "enterprise_value_to_ebitda": None,
        "enterprise_value": None,
        "enterprise_value_to_revenue": None,

        # ===== 수익성 지표 (DART) =====
        "return_on_equity": dart_data.get("return_on_equity"),
        "return_on_assets": dart_data.get("return_on_assets"),
        "return_on_invested_capital": dart_data.get("return_on_invested_capital"),
        "gross_margin": dart_data.get("gross_margin"),
        "operating_margin": dart_data.get("operating_margin"),
        "net_margin": dart_data.get("net_margin"),
        "ebitda": None,
        "ebitda_margins": None,

        # ===== 성장 지표 (DART) =====
        "revenue_growth": dart_data.get("revenue_growth"),
        "earnings_growth": dart_data.get("earnings_growth"),
        "earnings_per_share_growth": None,

        # ===== 재무 건전성 (DART) =====
        "current_ratio": dart_data.get("current_ratio"),
        "quick_ratio": None,
        "debt_to_equity": dart_data.get("debt_to_equity"),
        "interest_coverage": dart_data.get("interest_coverage"),
        "cash_ratio": None,
        "operating_cash_flow_ratio": None,
        "asset_turnover": dart_data.get("asset_turnover"),
        "debt_to_assets": None,

        # ===== 배당 (PyKRX) =====
        "dividend_yield": pykrx_data.get("dividend_yield"),
        "payout_ratio": None,

        # ===== 시가총액 및 주식 정보 =====
        "market_cap": market_cap,
        "shares_outstanding": None,
        "float_shares": None,

        # ===== 현금흐름 =====
        "free_cash_flow": None,
        "free_cash_flow_yield": None,
        "free_cash_flow_per_share": None,
        "operating_cashflow": None,

        # ===== 부채/현금 =====
        "total_debt": None,
        "total_cash": None,
        "total_cash_per_share": None,

        # ===== 매출/수익 =====
        "total_revenue": None,
        "revenue_per_share": None,
        "earnings_per_share": pykrx_data.get("earnings_per_share"),
        "forward_eps": None,
        "book_value_per_share": pykrx_data.get("book_value_per_share"),

        # ===== 소유권/공매도 지표 =====
        "held_percent_insiders": None,
        "held_percent_institutions": None,
        "short_ratio": None,
        "short_percent_of_float": None,

        # ===== 기술적 지표 =====
        "beta": None,
        "52_week_high": None,
        "52_week_low": None,
        "52_week_change": None,
        "50_day_average": None,
        "200_day_average": None,

        # ===== 섹터/인더스트리 정보 =====
        "sector": None,
        "industry": None,

        # ===== R&D 지표 (Fisher 분석용) =====
        "research_and_development": dart_data.get("research_and_development"),
        "research_and_development_ratio": dart_data.get("research_and_development_ratio"),
    }


# ============================================================================
# 공개 함수: 가격 데이터
# ============================================================================

def _prices_from_fdr(ticker: str, start_date: str, end_date: str) -> list:
    """FDR에서 수정주가 OHLCV 데이터 가져오기"""
    fdr = _get_fdr()
    df = fdr.DataReader(ticker, start_date, end_date)

    if df is None or df.empty:
        return []

    prices = []
    for date, row in df.iterrows():
        try:
            prices.append({
                "time": date.strftime("%Y-%m-%d"),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return prices


def _prices_from_pykrx(ticker: str, start_date: str, end_date: str) -> list:
    """PyKRX에서 미보정 OHLCV 데이터 가져오기"""
    pykrx = _get_pykrx()
    start_str = start_date.replace("-", "")
    end_str = end_date.replace("-", "")

    df = pykrx.get_market_ohlcv_by_date(start_str, end_str, ticker)

    if df is None or df.empty:
        return []

    prices = []
    for date, row in df.iterrows():
        try:
            prices.append({
                "time": date.strftime("%Y-%m-%d"),
                "open": float(row["시가"]),
                "high": float(row["고가"]),
                "low": float(row["저가"]),
                "close": float(row["종가"]),
                "volume": int(row["거래량"]),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return prices


def get_prices_kr(ticker: str, start_date: str, end_date: str) -> list:
    """
    한국 주식 가격 데이터 가져오기 (FDR → KRX → PyKRX 3단계 폴백)

    FDR은 수정주가(adjusted price)를 자동 반영하여 액면분할/합병 보정된 데이터를 제공합니다.
    KRX API와 PyKRX는 미보정 원시 가격을 반환하므로 폴백으로만 사용합니다.

    Args:
        ticker: 6자리 종목코드
        start_date: 시작 날짜 (YYYY-MM-DD)
        end_date: 종료 날짜 (YYYY-MM-DD)

    Returns:
        list[dict]: [{time, open, high, low, close, volume}, ...]
    """
    # KRX REST API는 단일 날짜만 지원하므로 가격 체인에서 제외
    result = _fetch_with_fallback(
        primary_fn=lambda: _prices_from_fdr(ticker, start_date, end_date),
        fallback_fn=lambda: _prices_from_pykrx(ticker, start_date, end_date),
        label=f"가격({ticker})",
    )
    return result or []


def batch_fetch_prices_kr(tickers: list, start_date: str, end_date: str) -> dict:
    """
    한국 주식 여러 종목의 가격 데이터를 가져오기

    PyKRX는 배치 API가 없으므로 순차 호출합니다.
    (PyKRX 내장 1초 딜레이 존재)

    Args:
        tickers: 6자리 종목코드 리스트
        start_date: 시작 날짜 (YYYY-MM-DD)
        end_date: 종료 날짜 (YYYY-MM-DD)

    Returns:
        dict: {ticker: [price_list]} 형태
    """
    result = {}
    for ticker in tickers:
        prices = get_prices_kr(ticker, start_date, end_date)
        if prices:
            result[ticker] = prices
    return result


# ============================================================================
# 공개 함수: 내부자 거래 (DART 주요주주 공시)
# ============================================================================

def get_insider_trades_kr(ticker: str, end_date: str, limit: int = 100) -> list:
    """
    한국 주식 내부자 거래 데이터 (DART 주요주주 공시)

    DART 공시 API에서 '주요사항보고서'의 주요주주 관련 공시를 조회합니다.

    Args:
        ticker: 6자리 종목코드
        end_date: 기준 날짜
        limit: 최대 조회 건수

    Returns:
        list[dict]: [{insider_name, transaction_type, ...}, ...]
    """
    try:
        dart = _get_dart_reader()
        _dart_rate_limit()

        # 공시 목록에서 주요주주 관련 항목 검색
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=365)

        # DART 공시 검색 (주요사항보고서 중 주요주주 관련)
        df = dart.list(ticker, start=start_dt.strftime("%Y%m%d"), end=end_dt.strftime("%Y%m%d"), kind="D")

        if df is None or df.empty:
            return []

        # 주요주주 관련 공시 필터링
        insider_keywords = ["최대주주", "주요주주", "임원", "자기주식"]
        mask = df["report_nm"].str.contains("|".join(insider_keywords), na=False)
        insider_df = df[mask].head(limit)

        trades = []
        for _, row in insider_df.iterrows():
            trades.append({
                "insider_name": row.get("flr_nm", ""),  # 공시 제출인
                "insider_title": "",
                "transaction_type": row.get("report_nm", ""),  # 보고서명
                "shares": None,
                "value": None,
                "transaction_price_per_share": None,
                "transaction_date": row.get("rcept_dt", ""),  # 접수일
                "ownership_type": None,
                "filing_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row.get('rcept_no', '')}",
            })

        return trades
    except Exception as e:
        print(f"   ⚠️ DART 내부자 거래 조회 실패 ({ticker}): {e}")
        return []


# ============================================================================
# 공개 함수: 뉴스 (네이버 뉴스 + DART 공시 병합)
# ============================================================================

def _get_company_name(ticker: str) -> str:
    """PyKRX에서 종목코드로 회사명 조회"""
    try:
        pykrx = _get_pykrx()
        name = pykrx.get_market_ticker_name(ticker)
        return name or ticker
    except Exception:
        return ticker


def _fetch_naver_news_api(query: str, end_date: str, limit: int = 30) -> list:
    """
    네이버 검색 API로 뉴스 가져오기

    NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 필요합니다.
    https://developers.naver.com/apps/ 에서 검색 API 애플리케이션을 등록하세요.

    Args:
        query: 검색어 (회사명)
        end_date: 기준 날짜 (YYYY-MM-DD)
        limit: 최대 조회 건수

    Returns:
        list[dict]: 뉴스 리스트
    """
    import requests

    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")

    if not client_id or not client_secret:
        return []

    try:
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        }
        params = {
            "query": query,
            "display": min(limit, 100),  # 최대 100건
            "sort": "date",  # 최신순
        }

        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        news_list = []
        for item in data.get("items", []):
            # HTML 태그 제거
            title = item.get("title", "").replace("<b>", "").replace("</b>", "")
            description = item.get("description", "").replace("<b>", "").replace("</b>", "")

            # 날짜 파싱 (RFC 822 형식: "Mon, 06 Jan 2025 09:00:00 +0900")
            pub_date = item.get("pubDate", "")
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(pub_date)
                date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                date_str = pub_date

            news_list.append({
                "title": title,
                "publisher": "네이버 뉴스",
                "link": item.get("originallink") or item.get("link", ""),
                "date": date_str,
                "summary": description,
                "content_type": "news",
                "thumbnail_url": None,
            })

        return news_list
    except Exception as e:
        print(f"   ⚠️ 네이버 검색 API 조회 실패: {e}")
        return []


def _fetch_naver_finance_news(ticker: str, limit: int = 20) -> list:
    """
    네이버 증권 종목 뉴스 API로 뉴스 가져오기 (API 키 불필요)

    api.stock.naver.com의 공개 JSON API를 사용합니다.
    응답은 클러스터 배열이며, 각 클러스터에 관련 뉴스 items가 묶여있습니다.

    Args:
        ticker: 6자리 종목코드
        limit: 최대 조회 건수

    Returns:
        list[dict]: 뉴스 리스트
    """
    import requests
    import html as html_mod

    try:
        page_size = min(limit, 30)
        url = f"https://api.stock.naver.com/news/stock/{ticker}"
        params = {"pageSize": page_size, "page": 1}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        }

        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        news_list = []

        # 응답은 클러스터 배열: [{total, items: [{id, officeId, articleId, officeName, datetime, title, body, ...}]}]
        if not isinstance(data, list):
            return []

        for cluster in data:
            items = cluster.get("items", [])
            for item in items:
                title = html_mod.unescape(item.get("title", "")).strip()
                if not title:
                    continue

                # datetime 형식: "202601281052" → "2026-01-28 10:52"
                raw_dt = item.get("datetime", "")
                date_str = raw_dt
                if len(raw_dt) >= 12:
                    date_str = f"{raw_dt[:4]}-{raw_dt[4:6]}-{raw_dt[6:8]} {raw_dt[8:10]}:{raw_dt[10:12]}"
                elif len(raw_dt) >= 8:
                    date_str = f"{raw_dt[:4]}-{raw_dt[4:6]}-{raw_dt[6:8]}"

                office_id = item.get("officeId", "")
                article_id = item.get("articleId", "")
                link = f"https://n.news.naver.com/mnews/article/{office_id}/{article_id}" if office_id and article_id else ""

                body = html_mod.unescape(item.get("body", "")).strip()

                news_list.append({
                    "title": title,
                    "publisher": item.get("officeName", "네이버 증권"),
                    "link": link,
                    "date": date_str,
                    "summary": body[:200] if body else "",
                    "content_type": "news",
                    "thumbnail_url": None,
                })

                if len(news_list) >= limit:
                    return news_list

        return news_list
    except Exception as e:
        print(f"   ⚠️ 네이버 증권 뉴스 API 조회 실패 ({ticker}): {e}")
        return []


def _fetch_dart_disclosures(ticker: str, end_date: str, limit: int = 20) -> list:
    """
    DART 공시 목록 가져오기

    Args:
        ticker: 6자리 종목코드
        end_date: 기준 날짜
        limit: 최대 조회 건수

    Returns:
        list[dict]: 공시 리스트
    """
    try:
        dart = _get_dart_reader()
        _dart_rate_limit()

        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=90)

        df = dart.list(ticker, start=start_dt.strftime("%Y%m%d"), end=end_dt.strftime("%Y%m%d"))

        if df is None or df.empty:
            return []

        news_list = []
        for _, row in df.head(limit).iterrows():
            rcept_no = row.get("rcept_no", "")
            rcept_dt = row.get("rcept_dt", "")
            # YYYYMMDD → YYYY-MM-DD 변환
            if len(rcept_dt) == 8:
                rcept_dt = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:8]}"

            news_list.append({
                "title": row.get("report_nm", ""),
                "publisher": "DART (금융감독원 전자공시)",
                "link": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else "",
                "date": rcept_dt,
                "summary": f"[{row.get('corp_name', '')}] {row.get('report_nm', '')}",
                "content_type": "disclosure",
                "thumbnail_url": None,
            })

        return news_list
    except Exception as e:
        print(f"   ⚠️ DART 공시 목록 조회 실패 ({ticker}): {e}")
        return []


def get_company_news_kr(ticker: str, end_date: str, limit: int = 50) -> list:
    """
    한국 주식 뉴스 데이터 (네이버 뉴스 + DART 공시 병합)

    데이터소스 우선순위:
    1. 네이버 검색 API (NAVER_CLIENT_ID/SECRET 설정 시)
    2. 네이버 금융 종목 뉴스 (API 키 불필요, 폴백)
    3. DART 공시 목록 (항상 포함)

    결과는 날짜 역순으로 정렬되며, content_type으로 뉴스("news")와 공시("disclosure")를 구분합니다.

    Args:
        ticker: 6자리 종목코드
        end_date: 기준 날짜
        limit: 최대 조회 건수

    Returns:
        list[dict]: [{title, publisher, link, date, summary, content_type, thumbnail_url}, ...]
    """
    all_news = []

    # 뉴스 건수 할당: 뉴스 60%, 공시 40%
    news_limit = max(5, int(limit * 0.6))
    disclosure_limit = max(5, limit - news_limit)

    # 1. 네이버 뉴스 (API 또는 스크래핑)
    company_name = _get_company_name(ticker)

    # 네이버 검색 API 시도
    naver_news = _fetch_naver_news_api(company_name, end_date, limit=news_limit)

    # API 키가 없거나 결과가 부족하면 네이버 금융 스크래핑으로 폴백
    if len(naver_news) < 3:
        finance_news = _fetch_naver_finance_news(ticker, limit=news_limit)
        # 중복 제거 (제목 기준)
        existing_titles = {n["title"] for n in naver_news}
        for n in finance_news:
            if n["title"] not in existing_titles:
                naver_news.append(n)
                existing_titles.add(n["title"])

    all_news.extend(naver_news[:news_limit])

    # 2. DART 공시 (항상 포함)
    dart_news = _fetch_dart_disclosures(ticker, end_date, limit=disclosure_limit)
    all_news.extend(dart_news)

    # 날짜 역순 정렬 (최신순)
    def _parse_date_for_sort(item):
        """정렬용 날짜 파싱 (다양한 형식 대응)"""
        date_str = item.get("date", "")
        if not date_str:
            return ""
        # YYYY-MM-DD HH:MM:SS 또는 YYYY-MM-DD 또는 YYYY.MM.DD
        return date_str.replace(".", "-")[:10]

    all_news.sort(key=_parse_date_for_sort, reverse=True)

    return all_news[:limit]


# ============================================================================
# 공개 함수: 시가총액
# ============================================================================

def _market_cap_from_pykrx(ticker: str, end_date: str) -> Optional[float]:
    """PyKRX에서 시가총액 조회 (내부 구현)"""
    pykrx = _get_pykrx()
    date_str = end_date.replace("-", "")

    df = pykrx.get_market_cap(date_str, date_str, ticker)
    if df is not None and not df.empty:
        cap = df.iloc[0].get("시가총액", None)
        if cap and cap > 0:
            return float(cap)
    return None


def get_market_cap_kr(ticker: str, end_date: str) -> Optional[float]:
    """
    한국 주식 시가총액 (KRX API → PyKRX 폴백)

    Args:
        ticker: 6자리 종목코드
        end_date: 기준 날짜

    Returns:
        시가총액 (원) 또는 None
    """
    sources = []
    if _krx_api_available():
        sources.append(("KRX", lambda: _market_cap_from_krx(ticker, end_date)))
    sources.append(("PyKRX", lambda: _market_cap_from_pykrx(ticker, end_date)))

    result = _fetch_with_chain(sources, label=f"시총({ticker})")
    return result


# ============================================================================
# 공개 함수: 인덱스 종목 리스트
# ============================================================================

def _tickers_from_fdr(market: str) -> list:
    """FDR에서 종목 리스트 가져오기 (상장/상폐 포함, 메타데이터 풍부)"""
    fdr = _get_fdr()
    market_upper = market.upper()

    # KOSPI200/KOSDAQ150은 인덱스 구성종목만 반환 (FDR은 인덱스별 조회 미지원 → 건너뜀)
    if market_upper in ("KOSPI200", "KOSDAQ150"):
        return []

    if market_upper == "KOSPI":
        listing_market = "KOSPI"
    elif market_upper == "KOSDAQ":
        listing_market = "KOSDAQ"
    else:
        listing_market = "KOSPI"

    df = fdr.StockListing(listing_market)

    if df is None or df.empty:
        return []

    # FDR StockListing은 Code 또는 Symbol 컬럼에 종목코드 포함
    code_col = None
    for col in ["Code", "Symbol", "ISU_SRT_CD", "종목코드"]:
        if col in df.columns:
            code_col = col
            break

    if code_col is None:
        return []

    tickers = df[code_col].dropna().astype(str).str.strip().tolist()
    # 6자리 종목코드만 필터링
    tickers = [t for t in tickers if len(t) == 6 and t.isdigit()]
    return tickers


def _tickers_from_pykrx(market: str) -> list:
    """PyKRX에서 종목 리스트 가져오기"""
    pykrx = _get_pykrx()
    today = datetime.now().strftime("%Y%m%d")

    market_upper = market.upper()

    # KOSPI200/KOSDAQ150: 인덱스 구성종목만 반환
    if market_upper == "KOSPI200":
        try:
            # KOSPI 200 인덱스 코드: 1028
            tickers = pykrx.get_index_portfolio_deposit_file("1028", today)
            if tickers is not None and len(tickers) > 0:
                return list(tickers)
        except Exception:
            pass
        # 폴백: 전체 KOSPI에서 시가총액 상위 200개
        return _top_n_by_market_cap(pykrx, today, "KOSPI", 200)

    if market_upper == "KOSDAQ150":
        try:
            # KOSDAQ 150 인덱스 코드: 2203
            tickers = pykrx.get_index_portfolio_deposit_file("2203", today)
            if tickers is not None and len(tickers) > 0:
                return list(tickers)
        except Exception:
            pass
        # 폴백: 전체 KOSDAQ에서 시가총액 상위 150개
        return _top_n_by_market_cap(pykrx, today, "KOSDAQ", 150)

    if market_upper == "KOSPI":
        tickers = pykrx.get_market_ticker_list(today, market="KOSPI")
    elif market_upper == "KOSDAQ":
        tickers = pykrx.get_market_ticker_list(today, market="KOSDAQ")
    else:
        tickers = pykrx.get_market_ticker_list(today, market="KOSPI")

    return tickers or []


def _top_n_by_market_cap(pykrx, date: str, market: str, n: int) -> list:
    """시가총액 상위 N개 종목 반환 (폴백용)"""
    try:
        df = pykrx.get_market_cap(date, market=market)
        if df is not None and not df.empty:
            df = df.sort_values("시가총액", ascending=False)
            return df.index.tolist()[:n]
    except Exception:
        pass
    return []


def get_index_tickers_kr(market: str = "KOSPI") -> list:
    """
    한국 시장 전 종목 리스트 (FDR → KRX → PyKRX 3단계 폴백)

    FDR은 상장/상폐 종목 포함 및 풍부한 메타데이터를 제공합니다.
    2024년 FDR JSONDecodeError 이슈 보고가 있어 try/except로 폴백을 지원합니다.

    Args:
        market: "KOSPI", "KOSDAQ", "KOSPI200", "KOSDAQ150"

    Returns:
        list[str]: 종목코드 리스트
    """
    sources = [("FDR", lambda: _tickers_from_fdr(market))]
    if _krx_api_available():
        sources.append(("KRX", lambda: _tickers_from_krx(market)))
    sources.append(("PyKRX", lambda: _tickers_from_pykrx(market)))

    result = _fetch_with_chain(sources, label=f"종목리스트({market})")
    return result or []


# ============================================================================
# 공개 함수: 재무제표 라인 아이템 검색 (investor-analysis 호환)
# ============================================================================

def search_line_items_kr(ticker: str, line_items: list, end_date: str, period: str = "annual", limit: int = 5) -> list:
    """
    DART 재무제표에서 라인 아이템 검색 (search_line_items 호환)

    Args:
        ticker: 6자리 종목코드
        line_items: 검색할 항목명 리스트
        end_date: 기준 날짜
        period: "annual" 또는 "quarterly"
        limit: 최대 기간 수

    Returns:
        list[dict]: 기간별 라인 아이템 데이터
    """
    try:
        dart = _get_dart_reader()

        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        year = end_dt.year
        if end_dt.month <= 3:
            year -= 1

        results = []

        # 최대 limit개 연도 조회
        for y in range(year, year - limit, -1):
            try:
                _dart_rate_limit()
                df = dart.finstate(ticker, y)

                if df is None or df.empty:
                    continue

                item_data = {
                    "ticker": ticker,
                    "report_period": f"{y}-12-31",
                    "period": period,
                }

                for item_name in line_items:
                    keywords = ACCOUNT_MAPPING.get(item_name, [item_name])
                    value = _find_account_value(df, keywords, "thstrm_amount")
                    item_data[item_name] = value

                results.append(item_data)
            except Exception:
                continue

        return results
    except Exception as e:
        print(f"   ⚠️ DART 라인 아이템 검색 실패 ({ticker}): {e}")
        return []


# ============================================================================
# 공개 함수: PyKRX → yfinance DataFrame 변환 (backtest 호환)
# ============================================================================

def _price_df_from_fdr(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """FDR에서 수정주가 DataFrame 가져오기"""
    fdr = _get_fdr()
    df = fdr.DataReader(ticker, start_date, end_date)

    if df is None or df.empty:
        return pd.DataFrame()

    # FDR은 이미 영문 컬럼(Open, High, Low, Close, Volume) 제공
    cols = ["Open", "High", "Low", "Close", "Volume"]
    available_cols = [c for c in cols if c in df.columns]
    return df[available_cols]


def _price_df_from_pykrx(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """PyKRX에서 미보정 가격 DataFrame 가져오기"""
    pykrx = _get_pykrx()
    start_str = start_date.replace("-", "")
    end_str = end_date.replace("-", "")

    df = pykrx.get_market_ohlcv_by_date(start_str, end_str, ticker)

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.rename(columns={
        "시가": "Open",
        "고가": "High",
        "저가": "Low",
        "종가": "Close",
        "거래량": "Volume",
    })

    cols = ["Open", "High", "Low", "Close", "Volume"]
    available_cols = [c for c in cols if c in df.columns]
    return df[available_cols]


def get_price_dataframe_kr(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    가격 데이터를 yfinance와 동일한 DataFrame 형식으로 반환 (FDR → KRX → PyKRX 폴백)

    backtest.py의 yf.download() 대체용.

    Args:
        ticker: 6자리 종목코드
        start_date: 시작 날짜 (YYYY-MM-DD)
        end_date: 종료 날짜 (YYYY-MM-DD)

    Returns:
        pd.DataFrame: Open, High, Low, Close, Volume 컬럼의 DataFrame
    """
    # KRX REST API는 단일 날짜만 지원하므로 가격DF 체인에서 제외
    result = _fetch_with_fallback(
        primary_fn=lambda: _price_df_from_fdr(ticker, start_date, end_date),
        fallback_fn=lambda: _price_df_from_pykrx(ticker, start_date, end_date),
        label=f"가격DF({ticker})",
    )
    return result if result is not None else pd.DataFrame()
