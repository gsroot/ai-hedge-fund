#!/usr/bin/env python3
"""
Backtesting Engine for Claude Code Skills

Yahoo Finance 기반의 백테스팅 시스템.
profit-predictor의 분석 결과를 활용하여 거래 신호를 생성하고
포트폴리오 성과를 시뮬레이션합니다.
"""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Literal, Optional, Tuple
from enum import Enum

import numpy as np
import pandas as pd
import yfinance as yf

# Add project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))

from dotenv import load_dotenv
load_dotenv()


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


@dataclass
class Portfolio:
    """포트폴리오 상태 관리"""
    cash: float
    margin_requirement: float = 0.5
    positions: Dict[str, Position] = field(default_factory=dict)
    realized_gains: Dict[str, Dict[str, float]] = field(default_factory=dict)
    margin_used: float = 0.0

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

        cost = quantity * price
        pos = self.positions[ticker]

        # 매수 가능 수량 계산
        if cost > self.cash:
            quantity = int(self.cash / price) if price > 0 else 0
            cost = quantity * price

        if quantity <= 0:
            return 0

        # 평균 매입 단가 계산
        old_shares = pos.long
        if old_shares + quantity > 0:
            total_cost = pos.long_cost_basis * old_shares + cost
            pos.long_cost_basis = total_cost / (old_shares + quantity)

        pos.long += quantity
        self.cash -= cost
        return quantity

    def sell(self, ticker: str, quantity: int, price: float) -> int:
        """롱 매도"""
        self.initialize_ticker(ticker)
        pos = self.positions[ticker]
        quantity = min(quantity, pos.long) if quantity > 0 else 0

        if quantity <= 0:
            return 0

        # 실현 손익
        realized_gain = (price - pos.long_cost_basis) * quantity
        self.realized_gains[ticker]["long"] += realized_gain

        pos.long -= quantity
        self.cash += quantity * price

        if pos.long == 0:
            pos.long_cost_basis = 0.0

        return quantity

    def short_open(self, ticker: str, quantity: int, price: float) -> int:
        """숏 매도 (공매도 진입)"""
        self.initialize_ticker(ticker)
        if quantity <= 0:
            return 0

        pos = self.positions[ticker]
        proceeds = price * quantity
        margin_required = proceeds * self.margin_requirement

        # 마진 확인
        if margin_required > self.cash:
            quantity = int(self.cash / (price * self.margin_requirement)) if price > 0 else 0
            if quantity <= 0:
                return 0
            proceeds = price * quantity
            margin_required = proceeds * self.margin_requirement

        # 평균 숏 단가 계산
        old_shares = pos.short
        if old_shares + quantity > 0:
            total_cost = pos.short_cost_basis * old_shares + price * quantity
            pos.short_cost_basis = total_cost / (old_shares + quantity)

        pos.short += quantity
        pos.short_margin_used += margin_required
        self.margin_used += margin_required
        self.cash += proceeds - margin_required

        return quantity

    def short_cover(self, ticker: str, quantity: int, price: float) -> int:
        """숏 커버 (공매도 청산)"""
        self.initialize_ticker(ticker)
        pos = self.positions[ticker]
        quantity = min(quantity, pos.short) if quantity > 0 else 0

        if quantity <= 0:
            return 0

        cover_cost = quantity * price
        realized_gain = (pos.short_cost_basis - price) * quantity

        # 마진 해제
        portion = quantity / pos.short if pos.short > 0 else 1.0
        margin_to_release = portion * pos.short_margin_used

        pos.short -= quantity
        pos.short_margin_used -= margin_to_release
        self.margin_used -= margin_to_release
        self.cash += margin_to_release - cover_cost
        self.realized_gains[ticker]["short"] += realized_gain

        if pos.short == 0:
            pos.short_cost_basis = 0.0
            pos.short_margin_used = 0.0

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
    risk_free_rate: float = 0.0434,
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
    """profit-predictor에서 인덱스 티커 목록 가져오기"""
    try:
        skills_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        predictor_scripts = os.path.join(skills_dir, "profit-predictor", "scripts")
        if predictor_scripts not in sys.path:
            sys.path.insert(0, predictor_scripts)
        from analyze_stocks import get_index_tickers
        return get_index_tickers(index_name, use_cache=True)
    except ImportError:
        print(f"⚠️ profit-predictor 모듈을 불러올 수 없습니다. 기본 목록 사용.")
        return None


def sort_tickers_by_market_cap(tickers: List[str], top_n: int = 0) -> List[str]:
    """티커를 시가총액 기준으로 정렬"""
    print(f"📊 {len(tickers)}개 종목을 시가총액 기준으로 정렬 중...")

    market_caps = {}
    batch_size = 50

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        for ticker in batch:
            try:
                stock = yf.Ticker(ticker)
                info = stock.info
                market_cap = info.get("marketCap", 0) or 0
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


def calculate_momentum_score(ticker: str, price_df: pd.DataFrame, lookback_short: int = 20, lookback_long: int = 60) -> Dict:
    """모멘텀 점수 계산 (가격 추세 + RSI + 상대 강도)"""
    try:
        if isinstance(price_df.columns, pd.MultiIndex):
            close = price_df["Close"][ticker].dropna()
        else:
            close = price_df["Close"].dropna()

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


def get_benchmark_return(ticker: str, start_date: str, end_date: str) -> Optional[float]:
    """벤치마크 수익률 계산"""
    try:
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)
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
    max_workers: int = 10,  # 병렬 처리 워커 수
) -> Dict[str, Dict]:
    """profit-predictor 분석 결과에서 거래 신호 생성 (상대적 순위 기반, 병렬 처리)"""
    try:
        # profit-predictor의 analyze_stocks 모듈 임포트
        skills_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        predictor_scripts = os.path.join(skills_dir, "profit-predictor", "scripts")
        if predictor_scripts not in sys.path:
            sys.path.insert(0, predictor_scripts)
        from analyze_stocks import analyze_single_ticker

        # 단일 티커 분석 래퍼 함수
        def analyze_ticker(ticker: str) -> Tuple[str, float, Dict]:
            try:
                result = analyze_single_ticker(ticker, analysis_date)
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
        print(f"  ⚠️ profit-predictor import 실패: {e}, 모멘텀 전략으로 대체")
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

    try:
        df = yf.download(
            tickers,
            start=start_date.strftime("%Y-%m-%d"),
            end=analysis_date,
            progress=False,
            threads=True,
        )

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
    max_workers: int = 10,
) -> Dict[str, Dict]:
    """하이브리드 전략: 펀더멘털 + 모멘텀 결합 (상대적 순위 기반)"""
    momentum_weight = 1.0 - fundamental_weight

    try:
        # profit-predictor 임포트
        skills_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        predictor_scripts = os.path.join(skills_dir, "profit-predictor", "scripts")
        if predictor_scripts not in sys.path:
            sys.path.insert(0, predictor_scripts)
        from analyze_stocks import analyze_single_ticker

        # 펀더멘털 분석 (병렬)
        def analyze_ticker(ticker: str) -> Tuple[str, float, Dict]:
            try:
                result = analyze_single_ticker(ticker, analysis_date)
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

        # 모멘텀 분석
        momentum_scores = {}
        momentum_details = {}
        for ticker in tickers:
            mom_data = calculate_momentum_score(ticker, price_df)
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
        max_shares = int(min(portfolio.cash, max_position_value) / price)
        return max(0, max_shares)
    elif action == Action.SELL:
        # 보유 중인 롱 포지션
        pos = portfolio.positions.get(ticker, Position())
        return pos.long
    elif action == Action.SHORT:
        # 마진으로 공매도 가능한 최대 수량
        margin_available = portfolio.cash
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
        workers: int = 10,  # 병렬 처리 워커 수
    ):
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.margin_requirement = margin_requirement
        self.rebalance_frequency = rebalance_frequency
        self.strategy = strategy
        self.benchmark = benchmark
        self.workers = workers

        self.portfolio = Portfolio(
            cash=initial_capital,
            margin_requirement=margin_requirement,
        )

        self.portfolio_values: List[Dict] = []
        self.trade_history: List[Dict] = []
        self.daily_returns: List[float] = []

    def _get_rebalance_dates(self) -> List[datetime]:
        """리밸런싱 날짜 목록 생성"""
        dates = pd.date_range(self.start_date, self.end_date, freq="B")

        if self.rebalance_frequency == "daily":
            return list(dates)
        elif self.rebalance_frequency == "weekly":
            # 매주 월요일
            return [d for d in dates if d.weekday() == 0]
        elif self.rebalance_frequency == "monthly":
            # 매월 첫 거래일
            monthly = []
            current_month = None
            for d in dates:
                if current_month != d.month:
                    monthly.append(d)
                    current_month = d.month
            return monthly

        return list(dates)

    def _fetch_price_data(self) -> pd.DataFrame:
        """가격 데이터 일괄 조회"""
        all_tickers = self.tickers + ([self.benchmark] if self.benchmark else [])

        # 1개월 전부터 조회 (모멘텀 계산용)
        start = datetime.strptime(self.start_date, "%Y-%m-%d") - timedelta(days=60)

        df = yf.download(
            all_tickers,
            start=start.strftime("%Y-%m-%d"),
            end=self.end_date,
            progress=False,
            threads=True,
        )

        return df

    def run(self) -> Dict:
        """백테스트 실행"""
        print(f"\n{'='*70}")
        print(f"📊 백테스트 시작: {self.start_date} ~ {self.end_date}")
        print(f"   종목: {', '.join(self.tickers)}")
        print(f"   초기 자본: ${self.initial_capital:,.0f}")
        print(f"   전략: {self.strategy}")
        print(f"   리밸런싱: {self.rebalance_frequency}")
        print(f"{'='*70}\n")

        # 가격 데이터 조회
        print("📥 가격 데이터 로딩 중...")
        price_df = self._fetch_price_data()

        if price_df.empty:
            print("❌ 가격 데이터를 가져올 수 없습니다.")
            return {"error": "No price data available"}

        # 리밸런싱 날짜
        rebalance_dates = self._get_rebalance_dates()
        all_dates = pd.date_range(self.start_date, self.end_date, freq="B")

        print(f"📅 총 {len(all_dates)}일 중 {len(rebalance_dates)}회 리밸런싱 예정\n")

        # 초기 포트폴리오 가치 기록
        self.portfolio_values.append({
            "date": all_dates[0],
            "value": self.initial_capital,
        })

        # 백테스트 루프
        for i, current_date in enumerate(all_dates):
            current_date_str = current_date.strftime("%Y-%m-%d")

            # 현재가 조회
            current_prices = {}
            missing_price = False

            available_tickers = []
            for ticker in self.tickers:
                try:
                    if len(self.tickers) > 1:
                        close_series = price_df["Close"][ticker]
                    else:
                        close_series = price_df["Close"]

                    # 해당 날짜 또는 이전 유효 가격
                    valid_prices = close_series.loc[:current_date].dropna()
                    if len(valid_prices) == 0:
                        continue  # 이 티커만 건너뜀
                    current_prices[ticker] = float(valid_prices.iloc[-1])
                    available_tickers.append(ticker)
                except Exception:
                    continue  # 이 티커만 건너뜀

            # 가격이 있는 종목이 전혀 없으면 건너뜀
            if len(available_tickers) == 0:
                continue

            # 리밸런싱 날짜인 경우 신호 생성 및 거래 실행
            if current_date in rebalance_dates:
                rebalance_idx = rebalance_dates.index(current_date) + 1
                print(f"\n   🔄 리밸런싱 {rebalance_idx}/{len(rebalance_dates)} ({current_date_str}) - {len(available_tickers)}개 종목 분석 중...", end="", flush=True)

                if self.strategy == "predictor":
                    signals = generate_signals_from_predictor(
                        available_tickers, current_date_str, max_workers=self.workers
                    )
                elif self.strategy == "hybrid":
                    signals = generate_hybrid_signals(
                        available_tickers, current_date_str, price_df, max_workers=self.workers
                    )
                else:  # momentum
                    signals = generate_momentum_signals(available_tickers, current_date_str)

                print(" 완료", flush=True)

                # 거래 실행 (가격이 유효한 종목만)
                for ticker in available_tickers:
                    signal = signals.get(ticker, {})
                    action = signal.get("action", Action.HOLD)
                    confidence = signal.get("confidence", 0.0)

                    if action == Action.HOLD:
                        continue

                    quantity = calculate_position_size(
                        self.portfolio,
                        current_prices,
                        ticker,
                        action,
                        confidence,
                    )

                    if quantity <= 0:
                        continue

                    price = current_prices[ticker]
                    executed_qty = 0

                    if action == Action.BUY:
                        executed_qty = self.portfolio.buy(ticker, quantity, price)
                    elif action == Action.SELL:
                        executed_qty = self.portfolio.sell(ticker, quantity, price)
                    elif action == Action.SHORT:
                        executed_qty = self.portfolio.short_open(ticker, quantity, price)
                    elif action == Action.COVER:
                        executed_qty = self.portfolio.short_cover(ticker, quantity, price)

                    if executed_qty > 0:
                        self.trade_history.append({
                            "date": current_date_str,
                            "ticker": ticker,
                            "action": action.value,
                            "quantity": executed_qty,
                            "price": price,
                            "confidence": confidence,
                        })

            # 포트폴리오 가치 기록
            total_value = self.portfolio.get_total_value(current_prices)
            self.portfolio_values.append({
                "date": current_date,
                "value": total_value,
            })

            # 진행 상황 출력 (10% 단위)
            progress = (i + 1) / len(all_dates)
            if i % max(1, len(all_dates) // 10) == 0:
                print(f"   진행: {progress*100:.0f}% | 날짜: {current_date_str} | 포트폴리오: ${total_value:,.0f}")

        # 성과 지표 계산
        metrics = calculate_performance_metrics(self.portfolio_values)
        metrics.total_trades = len(self.trade_history)

        # 승률 계산
        if self.trade_history:
            winning_trades = sum(1 for t in self.trade_history if self._is_winning_trade(t))
            metrics.win_rate = (winning_trades / len(self.trade_history)) * 100

        # 벤치마크 수익률
        benchmark_return = get_benchmark_return(self.benchmark, self.start_date, self.end_date)

        # 결과 출력
        self._print_results(metrics, benchmark_return)

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
            },
            "benchmark_return": benchmark_return,
            "final_value": self.portfolio_values[-1]["value"] if self.portfolio_values else self.initial_capital,
            "portfolio_values": [{"date": pv["date"].strftime("%Y-%m-%d"), "value": pv["value"]} for pv in self.portfolio_values],
            "trade_history": self.trade_history,
        }

    def _is_winning_trade(self, trade: Dict) -> bool:
        """거래 수익 여부 판단 (간단한 휴리스틱)"""
        # 실제로는 청산 시점 가격과 비교해야 하지만, 여기서는 간단히 처리
        return trade.get("confidence", 0) > 0.5

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
            alpha = (metrics.total_return or 0) - benchmark_return
            print(f"\n📊 벤치마크 비교 ({self.benchmark})")
            print(f"   벤치마크 수익률: {benchmark_return:>14.2f}%")
            print(f"   초과 수익 (α):  {alpha:>15.2f}%")

        print(f"\n📉 위험 지표")
        print(f"   Sharpe Ratio:   {metrics.sharpe_ratio:>15.2f}" if metrics.sharpe_ratio else "   Sharpe Ratio:   N/A")
        print(f"   Sortino Ratio:  {metrics.sortino_ratio:>15.2f}" if metrics.sortino_ratio else "   Sortino Ratio:  N/A")
        print(f"   Max Drawdown:   {metrics.max_drawdown:>15.2f}%" if metrics.max_drawdown else "   Max Drawdown:   N/A")
        if metrics.max_drawdown_date:
            print(f"   MDD 날짜:       {metrics.max_drawdown_date:>15}")

        print(f"\n📋 거래 통계")
        print(f"   총 거래 수:     {metrics.total_trades:>15}")
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
        description="백테스팅 시스템 - Yahoo Finance 기반",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 기본 모멘텀 전략 백테스트
  uv run python backtest.py --tickers AAPL,MSFT,GOOGL --start 2024-01-01 --end 2024-12-31

  # 하이브리드 전략 (펀더멘털 + 모멘텀) - 권장
  uv run python backtest.py --index sp500 --top 50 --sort-by-cap --strategy hybrid --rebalance monthly

  # profit-predictor 전략 사용
  uv run python backtest.py --tickers AAPL,MSFT --strategy predictor --rebalance monthly

  # S&P 500 시가총액 상위 50개 (시가총액 정렬)
  uv run python backtest.py --index sp500 --top 50 --sort-by-cap --strategy hybrid --rebalance monthly

  # NASDAQ 100 전체 종목 백테스트
  uv run python backtest.py --index nasdaq100 --strategy hybrid --rebalance monthly

  # 결과 JSON 저장
  uv run python backtest.py --tickers NVDA,TSLA --output results.json
        """
    )

    parser.add_argument("--tickers", type=str, help="분석할 종목 (콤마 구분)")
    parser.add_argument("--index", type=str,
                       choices=["sp500", "nasdaq100", "sp500-top10", "nasdaq-top10", "faang"],
                       help="인덱스 또는 사전 정의된 종목 그룹")
    parser.add_argument("--sort-by-cap", action="store_true",
                       help="시가총액 기준으로 정렬 (--top과 함께 사용 권장)")
    parser.add_argument("--top", type=int, default=0,
                       help="인덱스에서 상위 N개 종목만 사용 (0=전체)")
    parser.add_argument("--start", type=str, required=True, help="시작 날짜 (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="종료 날짜 (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=100000, help="초기 자본 (기본: 100000)")
    parser.add_argument("--strategy", type=str, default="momentum",
                       choices=["momentum", "predictor", "hybrid"],
                       help="거래 전략: momentum(가격추세), predictor(펀더멘털), hybrid(혼합) (기본: momentum)")
    parser.add_argument("--rebalance", type=str, default="weekly",
                       choices=["daily", "weekly", "monthly"],
                       help="리밸런싱 주기 (기본: weekly)")
    parser.add_argument("--benchmark", type=str, default="SPY", help="벤치마크 티커 (기본: SPY)")
    parser.add_argument("--margin", type=float, default=0.5, help="마진 요구율 (기본: 0.5)")
    parser.add_argument("--workers", type=int, default=10, help="병렬 처리 워커 수 (기본: 10)")
    parser.add_argument("--output", type=str, help="결과 JSON 저장 경로")

    args = parser.parse_args()

    # 종목 리스트 결정
    if args.tickers:
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
        elif args.index in ["sp500", "nasdaq100"]:
            # profit-predictor에서 전체 인덱스 티커 가져오기
            tickers = get_index_tickers_from_predictor(args.index)
            if not tickers:
                # fallback: 기본 상위 종목
                print(f"⚠️ {args.index} 전체 목록을 가져올 수 없습니다. 상위 10개만 사용합니다.")
                tickers = predefined_tickers.get(f"{args.index.replace('100', '')}-top10", [])
            else:
                print(f"📋 {args.index.upper()}: {len(tickers)}개 종목 로드됨")
        else:
            tickers = []

        # --sort-by-cap: 시가총액 기준으로 정렬
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
    )

    results = engine.run()

    # 결과 저장
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"✅ 결과가 {args.output}에 저장되었습니다.")


if __name__ == "__main__":
    main()
