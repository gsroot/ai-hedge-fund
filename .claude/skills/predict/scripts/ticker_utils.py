"""
한국 주식 티커 감지 및 정규화 유틸리티

6자리 숫자 종목코드를 감지하여 한국 주식 여부를 판별하고,
다양한 입력 형식(005930, 005930.KS, 005930.KQ)을 정규화합니다.
"""
import re


# 한국 종목코드 패턴: 6자리 숫자 (선택적으로 .KS/.KQ 접미사)
_KR_TICKER_PATTERN = re.compile(r"^\d{6}(\.KS|\.KQ)?$", re.IGNORECASE)


def is_korean_ticker(ticker: str) -> bool:
    """
    한국 주식 티커인지 판별

    Args:
        ticker: 종목코드 문자열 (예: "005930", "005930.KS", "AAPL")

    Returns:
        True if Korean ticker (6-digit numeric, optionally with .KS/.KQ suffix)
    """
    if not ticker or not isinstance(ticker, str):
        return False
    return bool(_KR_TICKER_PATTERN.match(ticker.strip()))


def normalize_korean_ticker(ticker: str) -> str:
    """
    한국 종목코드를 6자리 숫자로 정규화

    다양한 입력 형식을 순수 6자리 숫자로 변환합니다:
    - "005930" → "005930"
    - "005930.KS" → "005930"
    - "005930.KQ" → "005930"
    - "5930" → "005930" (zero-padding)

    Args:
        ticker: 종목코드 문자열

    Returns:
        6자리 zero-padded 종목코드 문자열
    """
    if not ticker or not isinstance(ticker, str):
        return ticker

    # .KS/.KQ 접미사 제거
    cleaned = re.sub(r"\.(KS|KQ)$", "", ticker.strip(), flags=re.IGNORECASE)

    # 숫자만 추출하여 6자리 zero-pad
    digits = re.sub(r"[^\d]", "", cleaned)
    if digits:
        return digits.zfill(6)

    return ticker.strip()


def is_korean_index(index_name: str) -> bool:
    """한국 주식 인덱스 이름인지 판별"""
    return index_name.lower() in ("kospi", "kosdaq", "kospi200", "kosdaq150", "krx")
