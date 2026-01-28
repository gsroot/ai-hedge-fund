"""
Yahoo Finance / DART Rate Limiting 대응 (재시도 로직)

지수 백오프, 스레드 안전 딜레이, 안전한 API 래퍼 함수를 제공합니다.
모든 Yahoo Finance API 호출은 이 모듈의 래퍼를 통해 수행됩니다.
DART API용 슬라이딩 윈도우 rate limiter도 포함합니다.
"""
import time
import random
import threading
from collections import deque

import yfinance as yf
import pandas as pd

from config import YF_REQUEST_DELAY, YF_MAX_RETRIES, YF_RETRY_BASE_DELAY, YF_JITTER_MAX, DART_RATE_LIMIT, DART_RATE_WINDOW

# 전역 락 (동시 요청 제어)
_yf_request_lock = threading.Lock()
_yf_last_request_time = 0.0


def _rate_limit_delay():
    """요청 간 딜레이 적용 (rate limiting 방지)"""
    global _yf_last_request_time
    with _yf_request_lock:
        now = time.time()
        elapsed = now - _yf_last_request_time
        if elapsed < YF_REQUEST_DELAY:
            sleep_time = YF_REQUEST_DELAY - elapsed + random.uniform(0, YF_JITTER_MAX)
            time.sleep(sleep_time)
        _yf_last_request_time = time.time()


def _retry_on_rate_limit(func, *args, max_retries=YF_MAX_RETRIES, **kwargs):
    """
    Yahoo Finance API 호출에 대한 재시도 로직

    401/429 오류 발생 시 지수 백오프로 재시도합니다.
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            _rate_limit_delay()
            return func(*args, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            # 401 Unauthorized 또는 429 Too Many Requests
            if '401' in error_str or '429' in error_str or 'unauthorized' in error_str or 'rate' in error_str:
                last_exception = e
                if attempt < max_retries:
                    # 지수 백오프: 2초, 4초, 8초...
                    delay = YF_RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, YF_JITTER_MAX)
                    time.sleep(delay)
                    continue
            # 다른 종류의 오류는 바로 raise
            raise e

    # 모든 재시도 실패
    if last_exception:
        raise last_exception
    return None


def safe_get_ticker_info(ticker: str) -> dict:
    """안전하게 티커 정보 가져오기 (재시도 로직 포함)"""
    def _fetch():
        stock = yf.Ticker(ticker)
        return stock.info

    try:
        return _retry_on_rate_limit(_fetch)
    except Exception:
        return {}


def safe_get_ticker_news(ticker: str) -> list:
    """안전하게 티커 뉴스 가져오기 (재시도 로직 포함)"""
    def _fetch():
        stock = yf.Ticker(ticker)
        return stock.news or []

    try:
        return _retry_on_rate_limit(_fetch)
    except Exception:
        return []


def safe_get_insider_transactions(ticker: str):
    """안전하게 내부자 거래 가져오기 (재시도 로직 포함)"""
    def _fetch():
        stock = yf.Ticker(ticker)
        return stock.insider_transactions

    try:
        return _retry_on_rate_limit(_fetch)
    except Exception:
        return None


def safe_get_ticker_history(ticker: str, start: str, end: str) -> pd.DataFrame:
    """안전하게 가격 히스토리 가져오기 (재시도 로직 포함)"""
    def _fetch():
        stock = yf.Ticker(ticker)
        return stock.history(start=start, end=end)

    try:
        result = _retry_on_rate_limit(_fetch)
        return result if result is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def safe_get_financials(ticker: str):
    """안전하게 재무제표 가져오기 (재시도 로직 포함)"""
    def _fetch():
        stock = yf.Ticker(ticker)
        return stock.financials

    try:
        return _retry_on_rate_limit(_fetch)
    except Exception:
        return None


def safe_get_balance_sheet(ticker: str):
    """안전하게 대차대조표 가져오기 (재시도 로직 포함)"""
    def _fetch():
        stock = yf.Ticker(ticker)
        return stock.balance_sheet

    try:
        return _retry_on_rate_limit(_fetch)
    except Exception:
        return None


def safe_batch_download(tickers: list, start: str, end: str, **kwargs) -> pd.DataFrame:
    """안전하게 배치 다운로드 (재시도 로직 포함)"""
    def _fetch():
        return yf.download(
            tickers=tickers,
            start=start,
            end=end,
            threads=True,
            progress=False,
            **kwargs
        )

    try:
        result = _retry_on_rate_limit(_fetch)
        return result if result is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


# ============================================================================
# DART API Rate Limiter (슬라이딩 윈도우, thread-safe)
# ============================================================================

_dart_request_times = deque()
_dart_lock = threading.Lock()


def dart_rate_limit():
    """
    DART API 슬라이딩 윈도우 rate limiter

    분당 DART_RATE_LIMIT(100)건 제한을 준수합니다.
    윈도우 내 요청이 제한에 도달하면 자동으로 대기합니다.
    """
    with _dart_lock:
        now = time.time()
        # 윈도우 밖의 오래된 타임스탬프 제거
        while _dart_request_times and _dart_request_times[0] < now - DART_RATE_WINDOW:
            _dart_request_times.popleft()

        # 제한 도달 시 대기
        if len(_dart_request_times) >= DART_RATE_LIMIT:
            sleep_until = _dart_request_times[0] + DART_RATE_WINDOW
            sleep_time = sleep_until - now
            if sleep_time > 0:
                time.sleep(sleep_time)

        _dart_request_times.append(time.time())
