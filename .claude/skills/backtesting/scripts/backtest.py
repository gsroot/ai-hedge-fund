#!/usr/bin/env python3
"""
Backtesting Engine for Claude Code Skills

Yahoo Finance 기반의 백테스팅 시스템.
predict의 분석 결과를 활용하여 거래 신호를 생성하고
포트폴리오 성과를 시뮬레이션합니다.
"""

import argparse
import json
import os
import sys
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Literal, Optional, Tuple
from enum import Enum
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# Add project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))

from dotenv import load_dotenv
load_dotenv()

# 한국 주식 지원 유틸리티 로드
_kr_utils_loaded = False
try:
    _skills_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _predictor_scripts = os.path.join(_skills_dir, "predict", "scripts")
    if _predictor_scripts not in sys.path:
        sys.path.insert(0, _predictor_scripts)
    from ticker_utils import is_korean_ticker, normalize_korean_ticker
    _kr_utils_loaded = True
except ImportError:
    def is_korean_ticker(ticker):
        return False
    def normalize_korean_ticker(ticker):
        return ticker


# ============================================================================
# Yahoo Finance Rate Limiting 대응 (재시도 로직)
# ============================================================================

YF_REQUEST_DELAY = 0  # 요청 간 딜레이 (워커 수 축소로 비활성화)
YF_MAX_RETRIES = 3  # 최대 재시도 횟수
YF_RETRY_BASE_DELAY = 2.0  # 재시도 시 기본 대기 시간 (초)
YF_JITTER_MAX = 0  # 랜덤 지터 (워커 수 축소로 비활성화)

_yf_request_lock = threading.Lock()
_yf_last_request_time = 0.0


def _rate_limit_delay():
    """요청 간 딜레이 적용"""
    global _yf_last_request_time
    with _yf_request_lock:
        now = time.time()
        elapsed = now - _yf_last_request_time
        if elapsed < YF_REQUEST_DELAY:
            sleep_time = YF_REQUEST_DELAY - elapsed + random.uniform(0, YF_JITTER_MAX)
            time.sleep(sleep_time)
        _yf_last_request_time = time.time()


def _retry_yf_call(func, *args, max_retries=YF_MAX_RETRIES, **kwargs):
    """Yahoo Finance API 호출에 대한 재시도 로직"""
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            _rate_limit_delay()
            return func(*args, **kwargs)
        except Exception as e:
            error_str = str(e).lower()
            if '401' in error_str or '429' in error_str or 'unauthorized' in error_str or 'rate' in error_str:
                last_exception = e
                if attempt < max_retries:
                    delay = YF_RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, YF_JITTER_MAX)
                    time.sleep(delay)
                    continue
            raise e

    if last_exception:
        raise last_exception
    return None


def _safe_get_ticker_info(ticker: str) -> dict:
    """안전하게 티커 정보 가져오기"""
    def _fetch():
        stock = yf.Ticker(ticker)
        return stock.info
    try:
        return _retry_yf_call(_fetch)
    except Exception:
        return {}


class Action(str, Enum):
    """거래 액션 타입"""
    BUY = "buy"
    SELL = "sell"
    SHORT = "short"
    COVER = "cover"
    HOLD = "hold"


@dataclass
class Position:
    """포지션 상태"""
    long: int = 0
    short: int = 0
    long_cost_basis: float = 0.0
    short_cost_basis: float = 0.0
    short_margin_used: float = 0.0
    short_proceeds: float = 0.0


@dataclass
class Portfolio:
    """포트폴리오 상태 관리"""
    cash: float
    margin_requirement: float = 0.5
    commission_bps: float = 5.0
    slippage_bps: float = 5.0
    sell_tax_bps: float = 0.0
    positions: Dict[str, Position] = field(default_factory=dict)
    realized_gains: Dict[str, Dict[str, float]] = field(default_factory=dict)
    margin_used: float = 0.0
    transaction_costs: float = 0.0
    last_trade: Dict[str, float] = field(default_factory=dict)

    def _execution_price(self, market_price: float, is_buy: bool) -> float:
        direction = 1.0 if is_buy else -1.0
        return market_price * (1.0 + direction * self.slippage_bps / 10000.0)

    def get_available_cash(self) -> float:
        """숏 매도대금과 유지 증거금을 재투자할 수 없는 보수적 가용 현금."""
        restricted_short_proceeds = sum(
            position.short_proceeds for position in self.positions.values()
        )
        return max(0.0, self.cash - restricted_short_proceeds - self.margin_used)

    def _record_trade(self, market_price, execution_price, fees, quantity, realized_pnl=None):
        slippage_cost = abs(execution_price - market_price) * quantity
        self.transaction_costs += fees + slippage_cost
        self.last_trade = {
            "market_price": market_price,
            "execution_price": execution_price,
            "fees": fees,
            "slippage_cost": slippage_cost,
            "realized_pnl": realized_pnl,
        }

    def initialize_ticker(self, ticker: str) -> None:
        """티커 초기화"""
        if ticker not in self.positions:
            self.positions[ticker] = Position()
        if ticker not in self.realized_gains:
            self.realized_gains[ticker] = {"long": 0.0, "short": 0.0}

    def buy(self, ticker: str, quantity: int, price: float) -> int:
        """롱 매수"""
        self.initialize_ticker(ticker)
        if quantity <= 0:
            return 0

        execution_price = self._execution_price(price, is_buy=True)
        commission_rate = self.commission_bps / 10000.0
        cost = quantity * execution_price
        commission = cost * commission_rate
        pos = self.positions[ticker]

        # 매수 가능 수량 계산
        available_cash = self.get_available_cash()
        if cost + commission > available_cash:
            all_in_price = execution_price * (1.0 + commission_rate)
            quantity = int(available_cash / all_in_price) if all_in_price > 0 else 0
            cost = quantity * execution_price
            commission = cost * commission_rate

        if quantity <= 0:
            return 0

        # 평균 매입 단가 계산
        old_shares = pos.long
        if old_shares + quantity > 0:
            total_cost = pos.long_cost_basis * old_shares + cost + commission
            pos.long_cost_basis = total_cost / (old_shares + quantity)

        pos.long += quantity
        self.cash -= cost + commission
        self._record_trade(price, execution_price, commission, quantity)
        return quantity

    def sell(self, ticker: str, quantity: int, price: float) -> int:
        """롱 매도"""
        self.initialize_ticker(ticker)
        pos = self.positions[ticker]
        quantity = min(quantity, pos.long) if quantity > 0 else 0

        if quantity <= 0:
            return 0

        execution_price = self._execution_price(price, is_buy=False)
        gross_proceeds = execution_price * quantity
        commission = gross_proceeds * self.commission_bps / 10000.0
        sell_tax = gross_proceeds * self.sell_tax_bps / 10000.0
        fees = commission + sell_tax

        # 매수 원가에는 진입 수수료가 포함되어 있다.
        realized_gain = gross_proceeds - fees - pos.long_cost_basis * quantity
        self.realized_gains[ticker]["long"] += realized_gain

        pos.long -= quantity
        self.cash += gross_proceeds - fees

        if pos.long == 0:
            pos.long_cost_basis = 0.0

        self._record_trade(price, execution_price, fees, quantity, realized_gain)
        return quantity

    def short_open(self, ticker: str, quantity: int, price: float) -> int:
        """숏 매도 (공매도 진입)"""
        self.initialize_ticker(ticker)
        if quantity <= 0:
            return 0

        pos = self.positions[ticker]
        execution_price = self._execution_price(price, is_buy=False)
        proceeds = execution_price * quantity
        commission = proceeds * self.commission_bps / 10000.0
        margin_required = proceeds * self.margin_requirement

        # 마진은 현금에서 사라지는 비용이 아니라 사용 가능 담보를 제한한다.
        margin_available = self.get_available_cash()
        if margin_required + commission > margin_available:
            denominator = execution_price * (
                self.margin_requirement + self.commission_bps / 10000.0
            )
            quantity = int(margin_available / denominator) if denominator > 0 else 0
            if quantity <= 0:
                return 0
            proceeds = execution_price * quantity
            commission = proceeds * self.commission_bps / 10000.0
            margin_required = proceeds * self.margin_requirement

        # 평균 숏 단가 계산
        old_shares = pos.short
        if old_shares + quantity > 0:
            total_cost = pos.short_cost_basis * old_shares + proceeds - commission
            pos.short_cost_basis = total_cost / (old_shares + quantity)

        pos.short += quantity
        pos.short_margin_used += margin_required
        pos.short_proceeds += proceeds
        self.margin_used += margin_required
        self.cash += proceeds - commission
        self._record_trade(price, execution_price, commission, quantity)

        return quantity

    def short_cover(self, ticker: str, quantity: int, price: float) -> int:
        """숏 커버 (공매도 청산)"""
        self.initialize_ticker(ticker)
        pos = self.positions[ticker]
        quantity = min(quantity, pos.short) if quantity > 0 else 0

        if quantity <= 0:
            return 0

        execution_price = self._execution_price(price, is_buy=True)
        cover_cost = quantity * execution_price
        commission = cover_cost * self.commission_bps / 10000.0
        realized_gain = pos.short_cost_basis * quantity - cover_cost - commission

        # 마진 해제
        portion = quantity / pos.short if pos.short > 0 else 1.0
        margin_to_release = portion * pos.short_margin_used
        proceeds_to_release = portion * pos.short_proceeds

        pos.short -= quantity
        pos.short_margin_used -= margin_to_release
        pos.short_proceeds -= proceeds_to_release
        self.margin_used -= margin_to_release
        self.cash -= cover_cost + commission
        self.realized_gains[ticker]["short"] += realized_gain

        if pos.short == 0:
            pos.short_cost_basis = 0.0
            pos.short_margin_used = 0.0
            pos.short_proceeds = 0.0

        self._record_trade(price, execution_price, commission, quantity, realized_gain)
        return quantity

    def get_total_value(self, current_prices: Dict[str, float]) -> float:
        """포트폴리오 총 가치 계산"""
        total = self.cash
        for ticker, pos in self.positions.items():
            price = current_prices.get(ticker, 0)
            total += pos.long * price
            total -= pos.short * price
        return total

    def get_exposures(self, current_prices: Dict[str, float]) -> Dict[str, float]:
        """익스포저 계산"""
        long_exposure = 0.0
        short_exposure = 0.0

        for ticker, pos in self.positions.items():
            price = current_prices.get(ticker, 0)
            long_exposure += pos.long * price
            short_exposure += pos.short * price

        gross = long_exposure + short_exposure
        net = long_exposure - short_exposure
        ls_ratio = long_exposure / short_exposure if short_exposure > 0 else float('inf')

        return {
            "long_exposure": long_exposure,
            "short_exposure": short_exposure,
            "gross_exposure": gross,
            "net_exposure": net,
            "long_short_ratio": ls_ratio,
        }


@dataclass
class PerformanceMetrics:
    """성과 지표"""
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    max_drawdown_date: Optional[str] = None
    total_return: Optional[float] = None
    annualized_return: Optional[float] = None
    win_rate: Optional[float] = None
    total_trades: int = 0


def calculate_performance_metrics(
    portfolio_values: List[Dict],
    trading_days: int = 252,
    risk_free_rate: float = 0.0,
) -> PerformanceMetrics:
    """성과 지표 계산"""
    if len(portfolio_values) < 2:
        return PerformanceMetrics()

    df = pd.DataFrame(portfolio_values)
    df["daily_return"] = df["value"].pct_change()
    clean_returns = df["daily_return"].dropna()

    if len(clean_returns) < 2:
        return PerformanceMetrics()

    # 일일 무위험 수익률
    daily_rf = risk_free_rate / trading_days
    excess_returns = clean_returns - daily_rf

    # Sharpe Ratio
    mean_excess = excess_returns.mean()
    std_excess = excess_returns.std()
    sharpe = np.sqrt(trading_days) * (mean_excess / std_excess) if std_excess > 1e-12 else 0.0

    # Sortino Ratio
    negative_returns = excess_returns[excess_returns < 0]
    downside_std = negative_returns.std() if len(negative_returns) > 0 else 0.0
    sortino = np.sqrt(trading_days) * (mean_excess / downside_std) if downside_std > 1e-12 else (float('inf') if mean_excess > 0 else 0.0)

    # Max Drawdown
    rolling_max = df["value"].cummax()
    drawdown = (df["value"] - rolling_max) / rolling_max
    max_dd = drawdown.min() * 100.0
    max_dd_date = drawdown.idxmin()
    max_dd_date_str = df.loc[max_dd_date, "date"].strftime("%Y-%m-%d") if max_dd < 0 else None

    # Total Return
    first_value = portfolio_values[0]["value"]
    last_value = portfolio_values[-1]["value"]
    total_return = ((last_value - first_value) / first_value) * 100.0

    # Annualized Return
    days = (portfolio_values[-1]["date"] - portfolio_values[0]["date"]).days
    if days > 0:
        annualized = ((1 + total_return / 100) ** (365 / days) - 1) * 100
    else:
        annualized = 0.0

    return PerformanceMetrics(
        sharpe_ratio=float(sharpe),
        sortino_ratio=float(sortino) if not np.isinf(sortino) else None,
        max_drawdown=float(max_dd),
        max_drawdown_date=max_dd_date_str,
        total_return=float(total_return),
        annualized_return=float(annualized),
    )


def get_index_tickers_from_predictor(index_name: str) -> List[str]:
    """predict에서 인덱스 티커 목록 가져오기"""
    try:
        skills_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        predictor_scripts = os.path.join(skills_dir, "predict", "scripts")
        if predictor_scripts not in sys.path:
            sys.path.insert(0, predictor_scripts)
        from analyze_stocks import get_index_tickers
        return get_index_tickers(index_name, use_cache=True)
    except ImportError:
        print(f"⚠️ predict 모듈을 불러올 수 없습니다. 기본 목록 사용.")
        return None


def sort_tickers_by_market_cap(tickers: List[str], top_n: int = 0) -> List[str]:
    """티커를 시가총액 기준으로 정렬 (한국/해외 자동 분기, 재시도 로직 포함)"""
    print(f"📊 {len(tickers)}개 종목을 시가총액 기준으로 정렬 중...")

    market_caps = {}
    batch_size = 50

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        for ticker in batch:
            try:
                if is_korean_ticker(ticker):
                    from korean_data_fetcher import get_market_cap_kr
                    kr_ticker = normalize_korean_ticker(ticker)
                    cap = get_market_cap_kr(kr_ticker, datetime.now().strftime("%Y-%m-%d"))
                    market_caps[ticker] = cap or 0
                else:
                    # 안전한 API 호출 (재시도 로직 포함)
                    info = _safe_get_ticker_info(ticker)
                    market_cap = info.get("marketCap", 0) or 0 if info else 0
                    market_caps[ticker] = market_cap
            except Exception:
                market_caps[ticker] = 0

    # 시가총액 기준 내림차순 정렬
    sorted_tickers = sorted(tickers, key=lambda t: market_caps.get(t, 0), reverse=True)

    if top_n > 0:
        sorted_tickers = sorted_tickers[:top_n]

    # 상위 10개 출력
    print(f"   시가총액 상위 10개: {sorted_tickers[:10]}")

    return sorted_tickers


def slice_price_frame_as_of(price_df: pd.DataFrame, analysis_date) -> pd.DataFrame:
    """분석 시점까지 공개된 가격만 남긴다."""
    if price_df.empty:
        return price_df
    cutoff = pd.Timestamp(analysis_date)
    index = pd.DatetimeIndex(price_df.index)
    if index.tz is not None and cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize(index.tz)
    return price_df.loc[index <= cutoff]


def _price_series(price_df: pd.DataFrame, field: str, ticker: str) -> pd.Series:
    """단일/멀티 컬럼 가격 프레임에서 종목 시계열을 추출한다."""
    if isinstance(price_df.columns, pd.MultiIndex):
        series = price_df[field][ticker]
    else:
        series = price_df[field]
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    return series


def calculate_momentum_score(ticker: str, price_df: pd.DataFrame, lookback_short: int = 20, lookback_long: int = 60) -> Dict:
    """모멘텀 점수 계산 (가격 추세 + RSI + 상대 강도)"""
    try:
        close = _price_series(price_df, "Close", ticker).dropna()

        if len(close) < lookback_long:
            return {"momentum_score": 0, "momentum": 0, "rsi": 50, "trend": "neutral"}

        # 단기 모멘텀 (20일)
        short_momentum = (close.iloc[-1] / close.iloc[-lookback_short] - 1) * 100

        # 장기 모멘텀 (60일)
        long_momentum = (close.iloc[-1] / close.iloc[-lookback_long] - 1) * 100

        # RSI (14일)
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs.iloc[-1])) if rs.iloc[-1] != 0 else 50

        # 추세 판단 (20일 이평선 vs 60일 이평선)
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1]
        trend = "bullish" if ma20 > ma60 else ("bearish" if ma20 < ma60 * 0.98 else "neutral")

        # 모멘텀 점수 계산 (0-10 스케일)
        # 단기 모멘텀: -30% ~ +30% → 0 ~ 5점
        short_score = max(0, min(5, (short_momentum + 30) / 12))

        # RSI 점수: 과매도(30) → 높은 점수, 과매수(70) → 낮은 점수
        # RSI 30-50: 좋음 (상승 여력), RSI 50-70: 보통, RSI > 70: 위험
        if rsi < 30:
            rsi_score = 2.5  # 과매도 - 반등 기대
        elif rsi < 50:
            rsi_score = 2.0  # 상승 여력
        elif rsi < 70:
            rsi_score = 1.0  # 보통
        else:
            rsi_score = 0.0  # 과매수 - 위험

        # 추세 점수
        trend_score = 2.5 if trend == "bullish" else (0.5 if trend == "bearish" else 1.5)

        momentum_score = short_score + rsi_score + trend_score

        return {
            "momentum_score": momentum_score,
            "short_momentum": short_momentum,
            "long_momentum": long_momentum,
            "rsi": rsi if not np.isnan(rsi) else 50,
            "trend": trend,
        }
    except Exception as e:
        return {"momentum_score": 0, "momentum": 0, "rsi": 50, "trend": "neutral", "error": str(e)}


def generate_momentum_signals_from_prices(
    tickers: List[str], price_df: pd.DataFrame, analysis_date
) -> Dict[str, Dict]:
    """이미 내려받은 과거 가격을 기준일로 절단해 모멘텀 신호를 만든다."""
    snapshot = slice_price_frame_as_of(price_df, analysis_date)
    signals = {}
    for ticker in tickers:
        detail = calculate_momentum_score(ticker, snapshot)
        momentum = detail.get("short_momentum", 0.0) / 100.0
        rsi = detail.get("rsi", 50.0)
        if momentum > 0.1 and rsi < 70:
            action = Action.BUY
            confidence = min(momentum, 0.3) / 0.3
        elif momentum < -0.1 and rsi > 30:
            action = Action.SELL
            confidence = min(abs(momentum), 0.3) / 0.3
        else:
            action = Action.HOLD
            confidence = 0.5
        signals[ticker] = {"action": action, "confidence": confidence, **detail}
    return signals


def get_benchmark_return(ticker: str, start_date: str, end_date: str) -> Optional[float]:
    """벤치마크 수익률 계산 (한국/해외 자동 분기)"""
    try:
        if is_korean_ticker(ticker):
            from korean_data_fetcher import get_prices_kr
            kr_ticker = normalize_korean_ticker(ticker)
            prices = get_prices_kr(kr_ticker, start_date, end_date)
            if not prices or len(prices) < 2:
                return None
            first_close = prices[0]["close"]
            last_close = prices[-1]["close"]
            return ((last_close - first_close) / first_close) * 100.0

        end_exclusive = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        df = yf.download(ticker, start=start_date, end=end_exclusive, progress=False)
        if df.empty:
            return None

        # Close 컬럼 추출 (MultiIndex 또는 단일 인덱스 처리)
        close_col = df["Close"]
        if isinstance(close_col, pd.DataFrame):
            close_col = close_col.iloc[:, 0]

        first_close = float(close_col.iloc[0])
        last_close = float(close_col.iloc[-1])
        return ((last_close - first_close) / first_close) * 100.0
    except Exception:
        return None


def generate_signals_from_predictor(
    tickers: List[str],
    analysis_date: str,
    top_pct: float = 0.4,  # 상위 40% 매수
    bottom_pct: float = 0.2,  # 하위 20% 매도
    max_workers: int = 3,  # 병렬 처리 워커 수 (rate limiting 대응)
    skip_news: bool = False,  # 뉴스/내부자 조회 건너뜀 (401 오류 방지)
) -> Dict[str, Dict]:
    """predict 분석 결과에서 거래 신호 생성 (상대적 순위 기반, 병렬 처리)"""
    try:
        # predict의 analyze_stocks 모듈 임포트
        skills_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        predictor_scripts = os.path.join(skills_dir, "predict", "scripts")
        if predictor_scripts not in sys.path:
            sys.path.insert(0, predictor_scripts)
        from analyze_stocks import analyze_single_ticker

        # 단일 티커 분석 래퍼 함수
        def analyze_ticker(ticker: str) -> Tuple[str, float, Dict]:
            try:
                result = analyze_single_ticker(
                    ticker,
                    analysis_date,
                    skip_news=skip_news,
                )
                if result:
                    return (ticker, result.get("total_score", 0), result)
                return (ticker, 0, {})
            except Exception as e:
                return (ticker, 0, {"error": str(e)})

        # 병렬 처리로 모든 티커 분석
        ticker_scores = []
        ticker_results = {}

        # 종목 수에 따라 워커 수 조정
        actual_workers = min(max_workers, len(tickers))

        with ThreadPoolExecutor(max_workers=actual_workers) as executor:
            futures = {executor.submit(analyze_ticker, t): t for t in tickers}
            for future in as_completed(futures):
                ticker, score, result = future.result()
                ticker_scores.append((ticker, score))
                ticker_results[ticker] = result

        # 점수 기준 정렬 (높은 순)
        ticker_scores.sort(key=lambda x: x[1], reverse=True)

        # 상대적 순위로 신호 결정
        n = len(ticker_scores)
        top_n = max(1, int(n * top_pct))
        bottom_n = max(1, int(n * bottom_pct))

        signals = {}
        for i, (ticker, score) in enumerate(ticker_scores):
            result = ticker_results.get(ticker, {})

            if i < top_n:
                # 상위 N% - 매수
                action = Action.BUY
                # 순위가 높을수록 신뢰도 높음
                confidence = 0.5 + 0.5 * (top_n - i) / top_n
            elif i >= n - bottom_n:
                # 하위 N% - 매도
                action = Action.SELL
                confidence = 0.3 + 0.3 * (i - (n - bottom_n)) / bottom_n
            else:
                # 중간 - 보유
                action = Action.HOLD
                confidence = 0.5

            signals[ticker] = {
                "action": action,
                "confidence": confidence,
                "score": score,
                "rank": i + 1,
                "reasoning": result.get("key_factors", []),
            }

        return signals
    except ImportError as e:
        print(f"  ⚠️ predict import 실패: {e}, 모멘텀 전략으로 대체")
        return generate_momentum_signals(tickers, analysis_date)


def generate_momentum_signals(
    tickers: List[str],
    analysis_date: str,
    lookback_days: int = 20,
) -> Dict[str, Dict]:
    """간단한 모멘텀 기반 신호 생성 (fallback)"""
    signals = {}
    end_date = datetime.strptime(analysis_date, "%Y-%m-%d")
    start_date = end_date - timedelta(days=lookback_days * 2)

    # 한국/해외 티커 분리
    kr_tickers = [t for t in tickers if is_korean_ticker(t)]
    us_tickers = [t for t in tickers if not is_korean_ticker(t)]

    try:
        df = pd.DataFrame()
        if us_tickers:
            df = yf.download(
                us_tickers,
                start=start_date.strftime("%Y-%m-%d"),
                end=analysis_date,
                progress=False,
                threads=True,
            )

        # 한국 티커용 가격 데이터 병합
        if kr_tickers:
            try:
                from korean_data_fetcher import get_price_dataframe_kr
                for ticker in kr_tickers:
                    kr_ticker = normalize_korean_ticker(ticker)
                    kr_df = get_price_dataframe_kr(kr_ticker, start_date.strftime("%Y-%m-%d"), analysis_date)
                    if kr_df.empty:
                        continue
                    if df.empty:
                        if len(tickers) > 1:
                            multi_cols = pd.MultiIndex.from_product([kr_df.columns, [ticker]])
                            df = pd.DataFrame(kr_df.values, index=kr_df.index, columns=multi_cols)
                        else:
                            df = kr_df
                    elif isinstance(df.columns, pd.MultiIndex):
                        for col in kr_df.columns:
                            df[(col, ticker)] = kr_df[col].reindex(df.index)
                    else:
                        # 단일 해외 티커 → 멀티인덱스 변환 후 병합
                        if us_tickers:
                            us_t = us_tickers[0]
                            new_cols = pd.MultiIndex.from_product([df.columns, [us_t]])
                            df_m = pd.DataFrame(df.values, index=df.index, columns=new_cols)
                            for col in kr_df.columns:
                                df_m[(col, ticker)] = kr_df[col].reindex(df_m.index)
                            df = df_m
            except ImportError:
                pass

        for ticker in tickers:
            try:
                if len(tickers) > 1:
                    close = df["Close"][ticker].dropna()
                else:
                    close = df["Close"].dropna()

                if len(close) < lookback_days:
                    signals[ticker] = {"action": Action.HOLD, "confidence": 0.0}
                    continue

                # 모멘텀: 현재가 / 20일 전 가격 - 1
                momentum = close.iloc[-1] / close.iloc[-lookback_days] - 1

                # RSI 계산
                delta = close.diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs.iloc[-1]))

                # 신호 결정
                if momentum > 0.1 and rsi < 70:
                    action = Action.BUY
                    confidence = min(momentum, 0.3) / 0.3
                elif momentum < -0.1 and rsi > 30:
                    action = Action.SELL
                    confidence = min(abs(momentum), 0.3) / 0.3
                else:
                    action = Action.HOLD
                    confidence = 0.5

                signals[ticker] = {
                    "action": action,
                    "confidence": confidence,
                    "momentum": float(momentum),
                    "rsi": float(rsi) if not np.isnan(rsi) else None,
                }
            except Exception as e:
                signals[ticker] = {"action": Action.HOLD, "confidence": 0.0, "error": str(e)}
    except Exception as e:
        for ticker in tickers:
            signals[ticker] = {"action": Action.HOLD, "confidence": 0.0, "error": str(e)}

    return signals


def generate_hybrid_signals(
    tickers: List[str],
    analysis_date: str,
    price_df: pd.DataFrame,
    fundamental_weight: float = 0.5,  # 펀더멘털 가중치 (나머지는 모멘텀)
    top_pct: float = 0.3,  # 상위 30% 매수
    bottom_pct: float = 0.2,  # 하위 20% 매도
    max_workers: int = 3,  # 병렬 처리 워커 수 (rate limiting 대응)
    skip_news: bool = False,  # 뉴스/내부자 조회 건너뜀 (401 오류 방지)
) -> Dict[str, Dict]:
    """하이브리드 전략: 펀더멘털 + 모멘텀 결합 (상대적 순위 기반)"""
    momentum_weight = 1.0 - fundamental_weight

    try:
        # predict 임포트
        skills_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        predictor_scripts = os.path.join(skills_dir, "predict", "scripts")
        if predictor_scripts not in sys.path:
            sys.path.insert(0, predictor_scripts)
        from analyze_stocks import analyze_single_ticker

        # 펀더멘털 분석 (병렬)
        def analyze_ticker(ticker: str) -> Tuple[str, float, Dict]:
            try:
                result = analyze_single_ticker(
                    ticker,
                    analysis_date,
                    skip_news=skip_news,
                )
                if result:
                    return (ticker, result.get("total_score", 0), result)
                return (ticker, 0, {})
            except Exception as e:
                return (ticker, 0, {"error": str(e)})

        fundamental_scores = {}
        fundamental_results = {}

        actual_workers = min(max_workers, len(tickers))
        with ThreadPoolExecutor(max_workers=actual_workers) as executor:
            futures = {executor.submit(analyze_ticker, t): t for t in tickers}
            for future in as_completed(futures):
                ticker, score, result = future.result()
                fundamental_scores[ticker] = score
                fundamental_results[ticker] = result

        # 모멘텀 분석: 반드시 분석 기준일까지 데이터 프레임을 절단한다.
        point_in_time_prices = slice_price_frame_as_of(price_df, analysis_date)
        momentum_scores = {}
        momentum_details = {}
        for ticker in tickers:
            mom_data = calculate_momentum_score(ticker, point_in_time_prices)
            momentum_scores[ticker] = mom_data.get("momentum_score", 0)
            momentum_details[ticker] = mom_data

        # 정규화 (0-10 스케일)
        def normalize_scores(scores: Dict[str, float]) -> Dict[str, float]:
            values = list(scores.values())
            if not values:
                return scores
            min_val, max_val = min(values), max(values)
            if max_val - min_val < 0.001:
                return {k: 5.0 for k in scores}
            return {k: (v - min_val) / (max_val - min_val) * 10 for k, v in scores.items()}

        norm_fundamental = normalize_scores(fundamental_scores)
        norm_momentum = normalize_scores(momentum_scores)

        # 하이브리드 점수 계산
        hybrid_scores = []
        for ticker in tickers:
            fund_score = norm_fundamental.get(ticker, 0)
            mom_score = norm_momentum.get(ticker, 0)
            hybrid = fund_score * fundamental_weight + mom_score * momentum_weight
            hybrid_scores.append((ticker, hybrid, fund_score, mom_score))

        # 하이브리드 점수 기준 정렬
        hybrid_scores.sort(key=lambda x: x[1], reverse=True)

        # 상대적 순위로 신호 결정
        n = len(hybrid_scores)
        top_n = max(1, int(n * top_pct))
        bottom_n = max(1, int(n * bottom_pct))

        signals = {}
        for i, (ticker, hybrid, fund, mom) in enumerate(hybrid_scores):
            if i < top_n:
                action = Action.BUY
                confidence = 0.6 + 0.4 * (top_n - i) / top_n
            elif i >= n - bottom_n:
                action = Action.SELL
                confidence = 0.3 + 0.3 * (i - (n - bottom_n)) / bottom_n
            else:
                action = Action.HOLD
                confidence = 0.5

            signals[ticker] = {
                "action": action,
                "confidence": confidence,
                "hybrid_score": hybrid,
                "fundamental_score": fundamental_scores.get(ticker, 0),
                "momentum_score": momentum_scores.get(ticker, 0),
                "rank": i + 1,
                "momentum_detail": momentum_details.get(ticker, {}),
            }

        return signals

    except ImportError as e:
        print(f"  ⚠️ hybrid 전략 실패: {e}, 모멘텀 전략으로 대체")
        return generate_momentum_signals(tickers, analysis_date)


def calculate_position_size(
    portfolio: Portfolio,
    current_prices: Dict[str, float],
    ticker: str,
    action: Action,
    confidence: float,
    max_position_pct: float = 0.2,
) -> int:
    """포지션 크기 계산"""
    price = current_prices.get(ticker, 0)
    if price <= 0:
        return 0

    total_value = portfolio.get_total_value(current_prices)
    max_position_value = total_value * max_position_pct * confidence

    if action == Action.BUY:
        # 현금으로 매수 가능한 최대 수량
        available_cash = portfolio.get_available_cash()
        max_shares = int(min(available_cash, max_position_value) / price)
        return max(0, max_shares)
    elif action == Action.SELL:
        # 보유 중인 롱 포지션
        pos = portfolio.positions.get(ticker, Position())
        return pos.long
    elif action == Action.SHORT:
        # 마진으로 공매도 가능한 최대 수량
        margin_available = portfolio.get_available_cash()
        max_short_value = margin_available / portfolio.margin_requirement
        max_shares = int(min(max_short_value, max_position_value) / price)
        return max(0, max_shares)
    elif action == Action.COVER:
        # 보유 중인 숏 포지션
        pos = portfolio.positions.get(ticker, Position())
        return pos.short

    return 0


class BacktestEngine:
    """백테스팅 엔진"""

    def __init__(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        initial_capital: float = 100000.0,
        margin_requirement: float = 0.5,
        rebalance_frequency: str = "weekly",  # daily, weekly, monthly
        strategy: str = "momentum",  # momentum, predictor
        benchmark: str = "SPY",
        workers: int = 3,  # 병렬 처리 워커 수 (rate limiting 대응)
        skip_news: bool = False,  # 뉴스/내부자 조회 건너뜀 (대량 백테스트 시 401 오류 방지)
        commission_bps: float = 5.0,
        slippage_bps: float = 5.0,
        sell_tax_bps: float = 0.0,
        risk_free_rate: float = 0.0,
        universe_has_survivorship_bias: bool = False,
        target_weights: Optional[Dict[str, float]] = None,
        portfolio_formation_date: Optional[str] = None,
    ):
        if pd.Timestamp(start_date) > pd.Timestamp(end_date):
            raise ValueError("start_date는 end_date보다 늦을 수 없습니다.")
        if initial_capital <= 0:
            raise ValueError("initial_capital은 0보다 커야 합니다.")
        if margin_requirement <= 0:
            raise ValueError("margin_requirement는 0보다 커야 합니다.")
        if target_weights is not None:
            if set(target_weights) != set(tickers):
                raise ValueError("target_weights 종목과 tickers가 일치해야 합니다.")
            if any(not isinstance(weight, (int, float)) or weight < 0 or weight > 1 for weight in target_weights.values()):
                raise ValueError("target_weights는 0~1 사이 소수여야 합니다.")
            if sum(target_weights.values()) > 1.0 + 1e-9:
                raise ValueError("target_weights 합계는 1을 넘을 수 없습니다.")
            if not portfolio_formation_date:
                raise ValueError("target_weights에는 portfolio_formation_date가 필요합니다.")
            if pd.Timestamp(portfolio_formation_date) >= pd.Timestamp(start_date):
                raise ValueError("target portfolio 백테스트 시작일은 포트폴리오 구성일보다 늦어야 합니다.")
            strategy = "target_weights"
        if strategy in {"predictor", "hybrid"} and any(not is_korean_ticker(t) for t in tickers):
            raise ValueError(
                "미국 종목의 과거 시점 재무 스냅샷이 없어 predictor/hybrid 백테스트를 차단했습니다. "
                "미국 종목은 momentum 전략을 사용하거나 point-in-time 데이터 공급자를 연결하세요."
            )
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.margin_requirement = margin_requirement
        self.rebalance_frequency = rebalance_frequency
        self.strategy = strategy
        self.benchmark = benchmark
        self.workers = workers
        self.skip_news = skip_news
        self.risk_free_rate = risk_free_rate
        self.universe_has_survivorship_bias = universe_has_survivorship_bias
        self.target_weights = target_weights
        self.portfolio_formation_date = portfolio_formation_date

        self.portfolio = Portfolio(
            cash=initial_capital,
            margin_requirement=margin_requirement,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            sell_tax_bps=sell_tax_bps,
        )

        self.portfolio_values: List[Dict] = []
        self.trade_history: List[Dict] = []
        self.daily_returns: List[float] = []

    def _get_rebalance_dates(self, dates: pd.DatetimeIndex) -> List[datetime]:
        """리밸런싱 날짜 목록 생성"""
        if self.rebalance_frequency == "daily":
            return list(dates)
        elif self.rebalance_frequency == "weekly":
            # 각 주의 실제 첫 거래일
            return list(pd.Series(dates, index=dates).groupby(dates.to_period("W")).first())
        elif self.rebalance_frequency == "monthly":
            # 매월 첫 거래일
            monthly = []
            current_month = None
            for d in dates:
                month_key = (d.year, d.month)
                if current_month != month_key:
                    monthly.append(d)
                    current_month = month_key
            return monthly

        return list(dates)

    def _fetch_price_data(self) -> pd.DataFrame:
        """가격 데이터 일괄 조회 (한국/해외 자동 분기)"""
        all_tickers = self.tickers + ([self.benchmark] if self.benchmark else [])

        # 1개월 전부터 조회 (모멘텀 계산용)
        start = datetime.strptime(self.start_date, "%Y-%m-%d") - timedelta(days=60)
        start_str = start.strftime("%Y-%m-%d")
        end_exclusive = (datetime.strptime(self.end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

        # 한국/해외 티커 분리
        kr_tickers = [t for t in all_tickers if is_korean_ticker(t)]
        us_tickers = [t for t in all_tickers if not is_korean_ticker(t)]

        df = pd.DataFrame()

        # 해외 티커: yfinance
        if us_tickers:
            df = yf.download(
                us_tickers,
                start=start_str,
                end=end_exclusive,
                progress=False,
                threads=True,
            )

        # 한국 티커: PyKRX
        if kr_tickers:
            try:
                from korean_data_fetcher import get_price_dataframe_kr

                for ticker in kr_tickers:
                    kr_ticker = normalize_korean_ticker(ticker)
                    kr_df = get_price_dataframe_kr(kr_ticker, start_str, self.end_date)

                    if kr_df.empty:
                        continue

                    if df.empty:
                        # 첫 번째 데이터: 멀티인덱스 구성
                        if len(all_tickers) > 1:
                            multi_cols = pd.MultiIndex.from_product([kr_df.columns, [ticker]])
                            kr_df_multi = pd.DataFrame(kr_df.values, index=kr_df.index, columns=multi_cols)
                            df = kr_df_multi
                        else:
                            df = kr_df
                    else:
                        # 기존 DataFrame에 한국 데이터 병합
                        if isinstance(df.columns, pd.MultiIndex):
                            for col in kr_df.columns:
                                df[(col, ticker)] = kr_df[col].reindex(df.index)
                        else:
                            # 단일 티커 → 멀티인덱스로 변환
                            if us_tickers:
                                us_ticker = us_tickers[0]
                                new_cols = pd.MultiIndex.from_product([df.columns, [us_ticker]])
                                df_multi = pd.DataFrame(df.values, index=df.index, columns=new_cols)
                                for col in kr_df.columns:
                                    df_multi[(col, ticker)] = kr_df[col].reindex(df_multi.index)
                                df = df_multi
                            else:
                                multi_cols = pd.MultiIndex.from_product([kr_df.columns, [ticker]])
                                kr_df_multi = pd.DataFrame(kr_df.values, index=kr_df.index, columns=multi_cols)
                                df = pd.concat([df, kr_df_multi], axis=1)
            except ImportError as e:
                print(f"   ⚠️ 한국 주식 데이터 모듈 로드 실패: {e}")

        return df

    def run(self) -> Dict:
        """백테스트 실행"""
        print(f"\n{'='*70}")
        print(f"📊 백테스트 시작: {self.start_date} ~ {self.end_date}")
        print(f"   종목: {', '.join(self.tickers)}")
        print(f"   초기 자본: ${self.initial_capital:,.0f}")
        print(f"   전략: {self.strategy}")
        print(f"   리밸런싱: {self.rebalance_frequency}")
        if self.strategy in {"predictor", "hybrid"}:
            print("   ⚠️ DART 보고연도는 기준일에 맞추지만 이후 정정공시 버전은 분리하지 못합니다.")
        print(f"{'='*70}\n")

        # 가격 데이터 조회
        print("📥 가격 데이터 로딩 중...")
        price_df = self._fetch_price_data()

        if price_df.empty:
            print("❌ 가격 데이터를 가져올 수 없습니다.")
            return {"error": "No price data available"}

        # 거래소의 실제 가격 인덱스를 사용한다. 주말만 제거한 가상 영업일은
        # 휴장일 체결과 이전 종가 재사용을 만들 수 있다.
        price_df = price_df.copy()
        price_df.index = pd.DatetimeIndex(price_df.index).tz_localize(None).normalize()
        start_ts = pd.Timestamp(self.start_date)
        end_ts = pd.Timestamp(self.end_date)
        all_price_dates = pd.DatetimeIndex(price_df.index.unique()).sort_values()
        all_dates = all_price_dates[(all_price_dates >= start_ts) & (all_price_dates <= end_ts)]
        if len(all_dates) == 0:
            return {"error": "No trading dates in requested range"}

        rebalance_dates = self._get_rebalance_dates(all_dates)
        rebalance_set = set(rebalance_dates)
        rebalance_number = {date: i + 1 for i, date in enumerate(rebalance_dates)}

        print(f"📅 총 {len(all_dates)}일 중 {len(rebalance_dates)}회 리밸런싱 예정\n")

        # 초기 포트폴리오 가치 기록
        self.portfolio_values.append({
            "date": all_dates[0],
            "value": self.initial_capital,
        })

        last_mark_prices: Dict[str, float] = {}

        def exact_price(ticker: str, field: str, date: pd.Timestamp) -> Optional[float]:
            try:
                series = _price_series(price_df, field, ticker)
                if date not in series.index:
                    return None
                value = series.loc[date]
                if isinstance(value, pd.Series):
                    value = value.iloc[-1]
                if pd.isna(value) or float(value) <= 0:
                    return None
                return float(value)
            except Exception:
                return None

        # 백테스트 루프
        for i, current_date in enumerate(all_dates):
            current_date_str = current_date.strftime("%Y-%m-%d")

            # 신호는 전 거래일 종가까지, 체결은 현재 거래일 시가로 분리한다.
            execution_prices = {}
            available_tickers = []
            for ticker in self.tickers:
                open_price = exact_price(ticker, "Open", current_date)
                if open_price is not None:
                    execution_prices[ticker] = open_price
                    available_tickers.append(ticker)

            sizing_prices = {**last_mark_prices, **execution_prices}

            # 리밸런싱 날짜인 경우 신호 생성 및 거래 실행
            if current_date in rebalance_set and available_tickers:
                previous_dates = all_price_dates[all_price_dates < current_date]
                if len(previous_dates) == 0:
                    continue
                signal_date = previous_dates[-1]
                signal_date_str = signal_date.strftime("%Y-%m-%d")
                rebalance_idx = rebalance_number[current_date]
                print(f"\n   🔄 리밸런싱 {rebalance_idx}/{len(rebalance_dates)} ({current_date_str}) - {len(available_tickers)}개 종목 분석 중...", end="", flush=True)

                if self.target_weights is not None:
                    portfolio_value = self.portfolio.get_total_value(sizing_prices)
                    signals = {}
                    for ticker in available_tickers:
                        current_quantity = self.portfolio.positions.get(ticker, Position()).long
                        target_value = portfolio_value * self.target_weights.get(ticker, 0.0)
                        target_quantity = int(target_value / execution_prices[ticker])
                        delta = target_quantity - current_quantity
                        action = Action.BUY if delta > 0 else (Action.SELL if delta < 0 else Action.HOLD)
                        signals[ticker] = {
                            "action": action,
                            "confidence": 1.0,
                            "score": self.target_weights.get(ticker, 0.0),
                            "target_weight": self.target_weights.get(ticker, 0.0),
                            "target_quantity_delta": abs(delta),
                        }
                elif self.strategy == "predictor":
                    signals = generate_signals_from_predictor(
                        available_tickers, signal_date_str, max_workers=self.workers, skip_news=self.skip_news
                    )
                elif self.strategy == "hybrid":
                    signals = generate_hybrid_signals(
                        available_tickers, signal_date_str, price_df, max_workers=self.workers, skip_news=self.skip_news
                    )
                else:  # momentum
                    signals = generate_momentum_signals_from_prices(available_tickers, price_df, signal_date)

                print(" 완료", flush=True)

                # 거래 실행 - 점수 순으로 정렬하여 처리 (현금 한도 내에서 최적 배분)
                # 1. 먼저 SELL 처리 (현금 확보)
                # 2. 그 다음 BUY를 점수 순으로 처리 (점수 높은 종목 우선 매수)

                # SELL 신호 먼저 처리
                for ticker in available_tickers:
                    signal = signals.get(ticker, {})
                    action = signal.get("action", Action.HOLD)
                    if action != Action.SELL:
                        continue

                    confidence = signal.get("confidence", 0.0)
                    quantity = signal.get("target_quantity_delta")
                    if quantity is None:
                        quantity = calculate_position_size(
                            self.portfolio, sizing_prices, ticker, action, confidence,
                        )
                    if quantity > 0:
                        price = execution_prices[ticker]
                        executed_qty = self.portfolio.sell(ticker, quantity, price)
                        if executed_qty > 0:
                            self.trade_history.append({
                                "date": current_date_str, "ticker": ticker,
                                "action": action.value, "quantity": executed_qty,
                                "signal_date": signal_date_str, "confidence": confidence,
                                "target_weight": signal.get("target_weight"),
                                **self.portfolio.last_trade,
                            })

                # BUY 신호를 점수 순으로 정렬하여 처리 (점수 높은 종목 우선)
                buy_signals = []
                for ticker in available_tickers:
                    signal = signals.get(ticker, {})
                    if signal.get("action") == Action.BUY:
                        # hybrid_score 또는 score 또는 confidence로 정렬
                        score = signal.get("hybrid_score") or signal.get("score") or signal.get("confidence", 0)
                        buy_signals.append((ticker, signal, score))

                # 점수 내림차순 정렬
                buy_signals.sort(key=lambda x: x[2], reverse=True)

                for ticker, signal, _ in buy_signals:
                    confidence = signal.get("confidence", 0.0)
                    quantity = signal.get("target_quantity_delta")
                    if quantity is None:
                        quantity = calculate_position_size(
                            self.portfolio, sizing_prices, ticker, Action.BUY, confidence,
                        )
                    if quantity > 0:
                        price = execution_prices[ticker]
                        executed_qty = self.portfolio.buy(ticker, quantity, price)
                        if executed_qty > 0:
                            self.trade_history.append({
                                "date": current_date_str, "ticker": ticker,
                                "action": Action.BUY.value, "quantity": executed_qty,
                                "signal_date": signal_date_str, "confidence": confidence,
                                "target_weight": signal.get("target_weight"),
                                **self.portfolio.last_trade,
                            })

            # 장 마감 가격으로 평가하되, 거래정지 종목은 마지막 관측 가격을 유지한다.
            for ticker in self.tickers:
                close_price = exact_price(ticker, "Close", current_date)
                if close_price is not None:
                    last_mark_prices[ticker] = close_price
            total_value = self.portfolio.get_total_value(last_mark_prices)
            self.portfolio_values.append({
                "date": current_date,
                "value": total_value,
            })

            # 진행 상황 출력 (10% 단위)
            progress = (i + 1) / len(all_dates)
            if i % max(1, len(all_dates) // 10) == 0:
                print(f"   진행: {progress*100:.0f}% | 날짜: {current_date_str} | 포트폴리오: ${total_value:,.0f}")

        # 성과 지표 계산
        metrics = calculate_performance_metrics(
            self.portfolio_values,
            risk_free_rate=self.risk_free_rate,
        )
        metrics.total_trades = len(self.trade_history)

        # 승률 계산
        closed_trades = [t for t in self.trade_history if t.get("realized_pnl") is not None]
        if closed_trades:
            winning_trades = sum(1 for t in closed_trades if t["realized_pnl"] > 0)
            metrics.win_rate = (winning_trades / len(closed_trades)) * 100

        # 벤치마크 수익률
        benchmark_return = get_benchmark_return(self.benchmark, self.start_date, self.end_date)

        # 결과 출력
        self._print_results(metrics, benchmark_return)

        benchmark_excess_return = (
            (metrics.total_return or 0) - benchmark_return
            if benchmark_return is not None else None
        )

        return {
            "metrics": {
                "sharpe_ratio": metrics.sharpe_ratio,
                "sortino_ratio": metrics.sortino_ratio,
                "max_drawdown": metrics.max_drawdown,
                "max_drawdown_date": metrics.max_drawdown_date,
                "total_return": metrics.total_return,
                "annualized_return": metrics.annualized_return,
                "win_rate": metrics.win_rate,
                "total_trades": metrics.total_trades,
                "closed_trades": len(closed_trades),
                "transaction_costs": self.portfolio.transaction_costs,
            },
            "benchmark_return": benchmark_return,
            "benchmark_excess_return": benchmark_excess_return,
            "validity": {
                "point_in_time_prices": True,
                "signal_execution_lag": "previous_close_to_next_open",
                "survivorship_bias": self.universe_has_survivorship_bias,
                "portfolio_formation_date": self.portfolio_formation_date,
                "fundamental_data": (
                    "not_used"
                    if self.strategy in {"momentum", "target_weights"}
                    else "report_year_lagged_but_revision_history_not_versioned"
                ),
            },
            "final_value": self.portfolio_values[-1]["value"] if self.portfolio_values else self.initial_capital,
            "portfolio_values": [{"date": pv["date"].strftime("%Y-%m-%d"), "value": pv["value"]} for pv in self.portfolio_values],
            "trade_history": self.trade_history,
        }

    def _print_results(self, metrics: PerformanceMetrics, benchmark_return: Optional[float]) -> None:
        """결과 출력"""
        print(f"\n{'='*70}")
        print(f"📈 백테스트 결과")
        print(f"{'='*70}")

        final_value = self.portfolio_values[-1]["value"] if self.portfolio_values else self.initial_capital

        print(f"\n💰 포트폴리오 성과")
        print(f"   초기 자본:      ${self.initial_capital:>15,.0f}")
        print(f"   최종 가치:      ${final_value:>15,.0f}")
        if metrics.total_return is not None:
            print(f"   총 수익률:      {metrics.total_return:>15.2f}%")
        else:
            total_ret = ((final_value - self.initial_capital) / self.initial_capital) * 100
            print(f"   총 수익률:      {total_ret:>15.2f}%")
        if metrics.annualized_return is not None:
            print(f"   연환산 수익률:  {metrics.annualized_return:>15.2f}%")
        else:
            print(f"   연환산 수익률:           N/A")

        if benchmark_return is not None:
            excess_return = (metrics.total_return or 0) - benchmark_return
            print(f"\n📊 벤치마크 비교 ({self.benchmark})")
            print(f"   벤치마크 수익률: {benchmark_return:>14.2f}%")
            print(f"   단순 초과 수익: {excess_return:>15.2f}%")

        print(f"\n📉 위험 지표")
        print(f"   Sharpe Ratio:   {metrics.sharpe_ratio:>15.2f}" if metrics.sharpe_ratio else "   Sharpe Ratio:   N/A")
        print(f"   Sortino Ratio:  {metrics.sortino_ratio:>15.2f}" if metrics.sortino_ratio else "   Sortino Ratio:  N/A")
        print(f"   Max Drawdown:   {metrics.max_drawdown:>15.2f}%" if metrics.max_drawdown else "   Max Drawdown:   N/A")
        if metrics.max_drawdown_date:
            print(f"   MDD 날짜:       {metrics.max_drawdown_date:>15}")

        print(f"\n📋 거래 통계")
        print(f"   총 거래 수:     {metrics.total_trades:>15}")
        print(f"   거래비용+슬리피지: ${self.portfolio.transaction_costs:>12,.2f}")
        if metrics.win_rate is not None:
            print(f"   승률:           {metrics.win_rate:>15.1f}%")

        # 포지션 현황
        print(f"\n📦 최종 포지션")
        for ticker, pos in self.portfolio.positions.items():
            if pos.long > 0 or pos.short > 0:
                print(f"   {ticker}: Long {pos.long}주, Short {pos.short}주")
        print(f"   현금: ${self.portfolio.cash:,.0f}")

        print(f"\n{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Point-in-time 가격 기반 백테스팅 시스템 (미국: Yahoo, 한국: DART/PyKRX)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 기본 모멘텀 전략 백테스트
  uv run python backtest.py --tickers AAPL,MSFT,GOOGL --start 2024-01-01 --end 2024-12-31

  # 현재 인덱스 구성종목 사용(생존편향을 명시적으로 인정한 탐색용 실행)
  uv run python backtest.py --index sp500 --top 50 --acknowledge-survivorship-bias --start 2024-01-01 --end 2024-12-31

  # 결과 JSON 저장
  uv run python backtest.py --tickers NVDA,TSLA --start 2024-01-01 --end 2024-12-31 --output results.json
        """
    )

    parser.add_argument("--tickers", type=str, help="분석할 종목 (콤마 구분)")
    parser.add_argument("--weights-json", type=str,
                       help="portfolio-report가 만든 고정 목표비중 JSON (weights는 0~1 소수)")
    parser.add_argument("--index", type=str,
                       choices=["sp500", "nasdaq100", "sp500-top10", "nasdaq-top10", "faang", "kospi", "kosdaq"],
                       help="인덱스 또는 사전 정의된 종목 그룹 (한국: kospi, kosdaq)")
    parser.add_argument("--acknowledge-survivorship-bias", action="store_true",
                       help="현재 인덱스 구성종목을 과거에도 존재한 것으로 사용하는 생존편향을 인정하고 탐색용 실행")
    parser.add_argument("--no-sort-by-cap", action="store_false", dest="sort_by_cap",
                       help="시가총액 정렬 비활성화 (기본: 시가총액 내림차순 정렬)")
    parser.set_defaults(sort_by_cap=True)
    parser.add_argument("--top", type=int, default=0,
                       help="인덱스에서 상위 N개 종목만 사용 (0=전체)")
    parser.add_argument("--start", type=str, required=True, help="시작 날짜 (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="종료 날짜 (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=100000, help="초기 자본 (기본: 100000)")
    parser.add_argument("--strategy", type=str, default="momentum",
                       choices=["momentum", "predictor", "hybrid", "target_weights"],
                       help="거래 전략: momentum(가격추세), predictor/hybrid(한국 종목만) (기본: momentum)")
    parser.add_argument("--rebalance", type=str, default="weekly",
                       choices=["daily", "weekly", "monthly"],
                       help="리밸런싱 주기 (기본: weekly)")
    parser.add_argument("--benchmark", type=str, default="SPY", help="벤치마크 티커 (기본: SPY)")
    parser.add_argument("--margin", type=float, default=0.5, help="마진 요구율 (기본: 0.5)")
    parser.add_argument("--commission-bps", type=float, default=5.0, help="편도 매매 수수료(bp, 기본: 5)")
    parser.add_argument("--slippage-bps", type=float, default=5.0, help="편도 슬리피지(bp, 기본: 5)")
    parser.add_argument("--sell-tax-bps", type=float, default=0.0, help="매도 거래세(bp, 기본: 0)")
    parser.add_argument("--risk-free-rate", type=float, default=0.0, help="연 무위험수익률(소수, 기본: 0.0)")
    parser.add_argument("--workers", type=int, default=3, help="병렬 처리 워커 수 (기본: 3, rate limiting 대응)")
    parser.add_argument("--output", type=str, help="결과 JSON 저장 경로")
    parser.add_argument("--skip-news", action="store_true",
                       help="뉴스/내부자 거래 조회 건너뜀 (대량 백테스트 시 Yahoo Finance 401 오류 방지)")

    args = parser.parse_args()

    if args.index and not args.acknowledge_survivorship_bias:
        parser.error(
            "--index는 현재 구성종목을 사용해 생존편향이 생깁니다. "
            "검증용이면 --tickers로 당시 유니버스를 지정하고, 탐색용이면 "
            "--acknowledge-survivorship-bias를 추가하세요."
        )
    if any(value < 0 for value in (args.commission_bps, args.slippage_bps, args.sell_tax_bps)):
        parser.error("거래비용 bp 값은 0 이상이어야 합니다.")
    if args.capital <= 0 or args.margin <= 0:
        parser.error("--capital과 --margin은 0보다 커야 합니다.")
    if pd.Timestamp(args.start) > pd.Timestamp(args.end):
        parser.error("--start는 --end보다 늦을 수 없습니다.")

    target_weights = None
    portfolio_formation_date = None
    if args.weights_json:
        weights_payload = json.loads(Path(args.weights_json).read_text(encoding="utf-8"))
        target_weights = {ticker.upper(): weight for ticker, weight in weights_payload.get("weights", {}).items()}
        portfolio_formation_date = weights_payload.get("analysis_date")
        if not target_weights or not portfolio_formation_date:
            parser.error("--weights-json에는 analysis_date와 비어 있지 않은 weights가 필요합니다.")
        if args.index:
            parser.error("--weights-json과 --index는 함께 사용할 수 없습니다.")
        args.strategy = "target_weights"
    elif args.strategy == "target_weights":
        parser.error("--strategy target_weights에는 --weights-json이 필요합니다.")

    # 종목 리스트 결정
    if target_weights is not None:
        tickers = list(target_weights)
        if args.tickers:
            requested_tickers = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
            if requested_tickers != set(tickers):
                parser.error("--tickers와 --weights-json의 종목이 일치해야 합니다.")
    elif args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    elif args.index:
        # 사전 정의 그룹
        predefined_tickers = {
            "sp500-top10": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B", "UNH", "JPM"],
            "nasdaq-top10": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "COST", "NFLX"],
            "faang": ["META", "AAPL", "AMZN", "NFLX", "GOOGL"],
        }

        if args.index in predefined_tickers:
            tickers = predefined_tickers[args.index]
        elif args.index in ["kospi", "kosdaq"]:
            # 한국 인덱스
            tickers = get_index_tickers_from_predictor(args.index)
            if not tickers:
                print(f"⚠️ {args.index.upper()} 종목 목록을 가져올 수 없습니다.")
                tickers = []
            else:
                print(f"📋 {args.index.upper()}: {len(tickers)}개 종목 로드됨")
        elif args.index in ["sp500", "nasdaq100"]:
            # predict에서 전체 인덱스 티커 가져오기
            tickers = get_index_tickers_from_predictor(args.index)
            if not tickers:
                # fallback: 기본 상위 종목
                print(f"⚠️ {args.index} 전체 목록을 가져올 수 없습니다. 상위 10개만 사용합니다.")
                tickers = predefined_tickers.get(f"{args.index.replace('100', '')}-top10", [])
            else:
                print(f"📋 {args.index.upper()}: {len(tickers)}개 종목 로드됨")
        else:
            tickers = []

        # 시가총액 기준 정렬 (기본값: 활성화, --no-sort-by-cap으로 비활성화)
        if args.sort_by_cap and tickers:
            tickers = sort_tickers_by_market_cap(tickers, top_n=args.top if args.top > 0 else 0)
        elif args.top > 0 and len(tickers) > args.top:
            # --top 옵션만 사용: 기존 순서에서 상위 N개
            print(f"📉 상위 {args.top}개 종목만 사용합니다.")
            tickers = tickers[:args.top]
    else:
        print("❌ --tickers 또는 --index를 지정해야 합니다.")
        sys.exit(1)

    if not tickers:
        print("❌ 유효한 종목이 없습니다.")
        sys.exit(1)

    if args.strategy in {"predictor", "hybrid"} and any(not is_korean_ticker(t) for t in tickers):
        parser.error(
            "미국 종목의 과거 point-in-time 재무데이터가 없어 predictor/hybrid를 실행할 수 없습니다. "
            "미국 종목은 --strategy momentum을 사용하세요."
        )

    # 백테스트 실행
    engine = BacktestEngine(
        tickers=tickers,
        start_date=args.start,
        end_date=args.end,
        initial_capital=args.capital,
        margin_requirement=args.margin,
        rebalance_frequency=args.rebalance,
        strategy=args.strategy,
        benchmark=args.benchmark,
        workers=args.workers,
        skip_news=args.skip_news,
        commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
        sell_tax_bps=args.sell_tax_bps,
        risk_free_rate=args.risk_free_rate,
        universe_has_survivorship_bias=bool(args.index),
        target_weights=target_weights,
        portfolio_formation_date=portfolio_formation_date,
    )

    results = engine.run()

    # 결과 저장
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"✅ 결과가 {args.output}에 저장되었습니다.")


if __name__ == "__main__":
    main()
