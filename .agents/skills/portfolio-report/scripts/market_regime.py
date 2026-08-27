#!/usr/bin/env python3
"""Point-in-time market regime and dynamic cash allocation."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


FORMULA_VERSION = "market-regime-cash-v1"
BASE_CASH_WEIGHT = 0.15
INSUFFICIENT_DATA_CASH_WEIGHT = 0.20
MAX_CASH_WEIGHT = 0.50
MIN_OBSERVATIONS = 200


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def cash_weight_from_scores(
    overheat_score: float,
    fear_score: float,
    outlook_score: float,
) -> float:
    """Map 0..1 heat/fear and -1..1 outlook scores to a cash target."""
    overheat = clamp(float(overheat_score), 0.0, 1.0)
    fear = clamp(float(fear_score), 0.0, 1.0)
    outlook = clamp(float(outlook_score), -1.0, 1.0)
    target = (
        BASE_CASH_WEIGHT
        + 0.25 * overheat
        + 0.20 * max(-outlook, 0.0)
        - 0.10 * max(outlook, 0.0)
        - 0.15 * fear
    )
    return round(clamp(target, 0.0, MAX_CASH_WEIGHT), 4)


def _rsi(closes: pd.Series, window: int = 14) -> float:
    changes = closes.diff().dropna().tail(window)
    if changes.empty:
        return 50.0
    average_gain = float(changes.clip(lower=0.0).mean())
    average_loss = float((-changes.clip(upper=0.0)).mean())
    if average_loss <= 1e-12:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def _insufficient_result(
    benchmark: str,
    observations: int,
    as_of_date: str | None,
) -> dict[str, Any]:
    cash = INSUFFICIENT_DATA_CASH_WEIGHT
    return {
        "formula_version": FORMULA_VERSION,
        "benchmark": benchmark,
        "as_of_date": as_of_date,
        "data_quality": "insufficient",
        "observations": observations,
        "regime": "insufficient_data",
        "target_cash_weight": cash,
        "target_equity_weight": round(1.0 - cash, 4),
        "scores": {"overheat": None, "fear": None, "outlook": None},
        "metrics": {},
        "rationale": [
            f"시장 국면 계산에 필요한 {MIN_OBSERVATIONS}개 가격 관측치를 충족하지 못함",
            "데이터 보완 전까지 보수적 기본 현금 20% 적용",
        ],
    }


def assess_market_regime(
    closes: pd.Series,
    *,
    benchmark: str = "SPY",
    as_of_date: str | pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Assess the market using only closes available at or before ``as_of_date``."""
    series = pd.Series(closes, dtype=float).dropna().sort_index()
    if as_of_date is not None and not isinstance(series.index, pd.DatetimeIndex):
        raise TypeError("as_of_date를 적용하려면 closes에 DatetimeIndex가 필요합니다.")
    if as_of_date is not None:
        series = series.loc[: pd.Timestamp(as_of_date)]
    series = series[series > 0]
    latest_date = (
        pd.Timestamp(series.index[-1]).strftime("%Y-%m-%d")
        if not series.empty and isinstance(series.index, pd.DatetimeIndex)
        else (str(as_of_date) if as_of_date is not None else None)
    )
    if len(series) < MIN_OBSERVATIONS:
        return _insufficient_result(benchmark, len(series), latest_date)

    latest = float(series.iloc[-1])
    sma_50 = float(series.tail(50).mean())
    sma_200 = float(series.tail(200).mean())
    distance_200 = latest / sma_200 - 1.0
    trend_cross = sma_50 / sma_200 - 1.0
    momentum_126 = latest / float(series.iloc[-127]) - 1.0
    rsi_14 = _rsi(series, 14)
    rolling_peak = float(series.tail(252).max())
    drawdown = latest / rolling_peak - 1.0
    realized_volatility_20 = float(
        series.pct_change(fill_method=None).dropna().tail(20).std(ddof=1)
        * math.sqrt(252)
    )

    overheat_components = {
        "distance_above_200d": clamp((distance_200 - 0.05) / 0.15, 0.0, 1.0),
        "rsi": clamp((rsi_14 - 60.0) / 20.0, 0.0, 1.0),
        "six_month_momentum": clamp((momentum_126 - 0.10) / 0.30, 0.0, 1.0),
    }
    fear_components = {
        "drawdown": clamp((-drawdown - 0.08) / 0.22, 0.0, 1.0),
        "rsi": clamp((40.0 - rsi_14) / 20.0, 0.0, 1.0),
        "realized_volatility": clamp(
            (realized_volatility_20 - 0.20) / 0.30, 0.0, 1.0
        ),
    }
    outlook_components = {
        "price_vs_200d": clamp(distance_200 / 0.10, -1.0, 1.0),
        "50d_vs_200d": clamp(trend_cross / 0.08, -1.0, 1.0),
        "six_month_momentum": clamp(momentum_126 / 0.20, -1.0, 1.0),
    }
    overheat = sum(overheat_components.values()) / len(overheat_components)
    fear = sum(fear_components.values()) / len(fear_components)
    outlook = sum(outlook_components.values()) / len(outlook_components)
    target_cash = cash_weight_from_scores(overheat, fear, outlook)

    if overheat >= 0.55:
        regime = "overheated"
    elif fear >= 0.55 and outlook >= 0.0:
        regime = "fear_recovery"
    elif fear >= 0.55:
        regime = "fear_risk_off"
    elif outlook <= -0.35:
        regime = "risk_off"
    elif outlook >= 0.35:
        regime = "risk_on"
    else:
        regime = "neutral"

    rationale = []
    if overheat >= 0.35:
        rationale.append("가격의 장기 추세 이격·RSI·6개월 상승률이 과열 현금 확대 요인")
    if fear >= 0.35:
        rationale.append("낙폭·과매도·실현변동성의 공포 점수가 현금 확대 폭을 상쇄")
    if outlook >= 0.20:
        rationale.append("200일 추세·50/200일 추세·6개월 모멘텀이 긍정적이라 현금 축소")
    elif outlook <= -0.20:
        rationale.append("중장기 추세와 모멘텀이 부정적이라 현금 확대")
    if not rationale:
        rationale.append("과열·공포·전망 신호가 중립 범위라 기준 현금비중에 근접")

    return {
        "formula_version": FORMULA_VERSION,
        "benchmark": benchmark,
        "as_of_date": latest_date,
        "data_quality": "complete",
        "observations": len(series),
        "regime": regime,
        "target_cash_weight": target_cash,
        "target_equity_weight": round(1.0 - target_cash, 4),
        "scores": {
            "overheat": round(overheat, 6),
            "fear": round(fear, 6),
            "outlook": round(outlook, 6),
        },
        "components": {
            "overheat": {key: round(value, 6) for key, value in overheat_components.items()},
            "fear": {key: round(value, 6) for key, value in fear_components.items()},
            "outlook": {key: round(value, 6) for key, value in outlook_components.items()},
        },
        "metrics": {
            "close": latest,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "distance_to_sma_200": distance_200,
            "sma_50_to_sma_200": trend_cross,
            "momentum_126": momentum_126,
            "rsi_14": rsi_14,
            "drawdown_from_252d_peak": drawdown,
            "realized_volatility_20": realized_volatility_20,
        },
        "rationale": rationale,
    }
