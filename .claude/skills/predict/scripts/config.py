"""
공유 상수 및 설정

모든 모듈에서 참조하는 전역 설정값, 팩터 가중치, 투자자 가중치 등을 관리합니다.
"""
import os

# ============================================================================
# 캐시 설정
# ============================================================================

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
CACHE_ENABLED = True  # 글로벌 캐시 활성화 플래그

# ============================================================================
# Yahoo Finance Rate Limiting 설정
# ============================================================================

YF_REQUEST_DELAY = 0  # 요청 간 딜레이 (워커 수 축소로 비활성화)
YF_MAX_RETRIES = 3  # 최대 재시도 횟수
YF_RETRY_BASE_DELAY = 2.0  # 재시도 시 기본 대기 시간 (초)
YF_JITTER_MAX = 0  # 랜덤 지터 (워커 수 축소로 비활성화)

# ============================================================================
# 분석 기본 설정
# ============================================================================

MAX_WORKERS = 3  # Yahoo Finance rate limiting 대응을 위해 기본값 축소 (10 → 3)
DEFAULT_PERIOD = "1Y"

# ============================================================================
# 팩터별 가중치 (앙상블 분석)
# ============================================================================

FACTOR_WEIGHTS = {
    "value": 0.25,      # 버핏, 그레이엄, 멍거 스타일
    "growth": 0.20,     # 린치, 캐시우드 스타일
    "quality": 0.20,    # 멍거, 피셔 스타일
    "momentum": 0.10,   # 드러켄밀러 스타일
    "safety": 0.10,     # 파브라이, 버핏 스타일
    "sentiment": 0.08,  # 뉴스 센티먼트
    "insider": 0.07,    # 내부자 거래
}

# ============================================================================
# 투자자별 가중치 (5명 최적화 앙상블)
# 선정 기준: 장기 검증된 수익률(15년+), 독특한 투자 철학, 정량화 가능성
# ============================================================================

INVESTOR_WEIGHTS = {
    "buffett": 1.00,       # 50년+ 검증, 연평균 ~20%, 품질+가치+moat
    "lynch": 1.05,         # 13년 연평균 29%, GARP/PEG (최고 수익률 반영)
    "graham": 0.90,        # 가치투자 원조, 딥밸류+안전마진
    "druckenmiller": 0.70, # 30년+ 연평균 30%, 모멘텀/매크로 (팩터 이중가중치 방지)
    "fisher": 0.85,        # 성장주 투자 원조, 경영진/R&D 품질
}

# ============================================================================
# 센티먼트 분석 키워드
# ============================================================================

NEGATIVE_KEYWORDS = [
    "lawsuit", "fraud", "negative", "downturn", "decline", "investigation",
    "recall", "bankruptcy", "layoff", "cut", "warning", "miss", "loss",
    "scandal", "probe", "fine", "penalty", "default", "downgrade"
]

POSITIVE_KEYWORDS = [
    "beat", "exceed", "growth", "profit", "upgrade", "record", "expansion",
    "innovation", "breakthrough", "partnership", "acquisition", "dividend",
    "buyback", "raise", "strong", "surge", "rally", "outperform"
]

# ============================================================================
# 한국 주식 데이터 설정 (DART API + PyKRX)
# ============================================================================

DART_RATE_LIMIT = 100  # DART API 분당 최대 요청 수
DART_RATE_WINDOW = 60  # 슬라이딩 윈도우 크기 (초)
KR_CORPORATE_TAX_RATE = 0.22  # 한국 법인세율 (ROIC 계산용)

# KRX Open API 설정 (data-dbg.krx.co.kr REST API)
# KRX_API_KEY 환경변수 설정 시 시가총액 및 종목리스트 폴백 활성화:
#   OHLCV:    FDR → PyKRX (KRX는 단일날짜 전종목만 지원, 날짜 범위 불가)
#   시가총액: KRX → PyKRX
#   종목리스트: FDR → KRX → PyKRX
#   PER/PBR:  PyKRX (KRX REST API 미제공)
# KRX_API_KEY 미설정 시 기존 2단계 폴백(FDR → PyKRX) 유지
KRX_RATE_LIMIT_DELAY = 1.0  # KRX API 요청 간 딜레이 (초)

# 한국 주식 데이터 소스 우선순위
# "fdr" = FinanceDataReader (수정주가 자동 보정, 빠름)
# "pykrx" = PyKRX (미보정 원시가격, 1초/요청 딜레이)
# "krx" = KRX Open API (공식 데이터, KRX_API_KEY 필요, 시총/종목리스트만)
KR_PRICE_PRIMARY = "fdr"           # 가격 데이터 primary 소스
KR_TICKER_LIST_PRIMARY = "fdr"     # 종목 리스트 primary 소스
KR_MARKET_CAP_PRIMARY = "krx"      # 시가총액 primary 소스 (KRX_API_KEY 필요)
