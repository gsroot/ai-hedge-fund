---
name: profit-predictor
description: |
  특정 기간 후 최고 수익 예상 종목 선정. 전설적 투자자들의 분석 방식을 종합하여 예측.
  사용 시점: "3개월 후 가장 수익률 좋을 종목은?", 포트폴리오 순위, 투자 우선순위 결정,
  "어떤 종목을 사야 할까?", "AAPL, GOOGL, MSFT 중 뭘 사야해?", 수익률 예측
---

# Profit Predictor Skill

다중 투자자 앙상블 분석을 기반으로 종목 수익률을 예측하고 순위를 산정하는 시스템.

## 워크플로우

### Step 1: 종목 데이터 수집

각 종목에 대해 `investor-analysis` 스킬의 data_fetcher.py 활용:

```python
from .claude.skills.investor-analysis.scripts.data_fetcher import fetch_all_data

for ticker in tickers:
    data = fetch_all_data(ticker, end_date)
```

### Step 2: 다중 투자자 분석

17개 투자자/분석가 서브에이전트를 병렬로 호출:

```python
# 병렬 호출
signals = {}
for agent in investor_agents:
    signals[agent] = Task(
        subagent_type=agent,
        prompt=f"{ticker} 분석. 날짜: {end_date}"
    )
```

### Step 3: 앙상블 점수 계산

`scripts/ranking_algorithm.py` 사용:

```python
from scripts.ranking_algorithm import calculate_ensemble_score, predict_return

ensemble = calculate_ensemble_score(signals)
predicted_return = predict_return(
    ensemble_score=ensemble["ensemble_score"],
    volatility=0.3,  # 기본값
    momentum_factor=0.0  # 모멘텀 에이전트에서 가져오기
)
```

### Step 4: 순위 산정 및 출력

```python
from scripts.ranking_algorithm import rank_tickers

rankings = rank_tickers(ticker_signals, period="3M")
```

## 앙상블 알고리즘

### 신호 수치화

| 신호 | 값 |
|------|-----|
| bullish | +1.0 |
| neutral | 0.0 |
| bearish | -1.0 |

### 투자자별 가중치

| 투자자 | 가중치 | 근거 |
|--------|--------|------|
| Warren Buffett | 1.00 | 장기 복리 성과 최고 |
| Charlie Munger | 0.95 | 버핏 파트너, 정신 모형 |
| Aswath Damodaran | 0.90 | DCF 전문가 |
| Peter Lynch | 0.85 | GARP 선구자 |
| Ben Graham | 0.85 | 가치 투자의 아버지 |
| Stanley Druckenmiller | 0.80 | 매크로, 모멘텀 |
| Mohnish Pabrai | 0.78 | Dhandho 투자자 |
| Michael Burry | 0.75 | 역발상 전문 |
| Bill Ackman | 0.75 | 행동주의 투자 |
| Rakesh Jhunjhunwala | 0.72 | 신흥시장 전문 |
| Cathie Wood | 0.70 | 혁신 투자 (고위험) |

### 앙상블 점수 계산

```
앙상블 점수 = Σ(신호값 × 신뢰도 × 투자자가중치) / Σ(신뢰도 × 가중치)
```

범위: -1.0 ~ +1.0

### 수익률 예측

```python
def predict_return(ensemble_score, volatility, momentum_factor):
    # 기본 수익률: 앙상블 점수 기반 (최대 ±20%)
    base_return = ensemble_score * 0.20

    # 리스크 조정: 변동성이 높으면 수익률 감소
    risk_adjusted = base_return * (1 - volatility * 0.5)

    # 모멘텀 조정
    momentum_adjusted = risk_adjusted * (1 + momentum_factor * 0.3)

    return momentum_adjusted
```

## 신호 결정 기준

| 앙상블 점수 | 신호 | 예상 행동 |
|------------|------|----------|
| > 0.6 | 강한 매수 | 포트폴리오 상위 순위 |
| 0.3 ~ 0.6 | 매수 | 중상위 순위 |
| -0.3 ~ 0.3 | 중립 | 하위 순위 |
| -0.6 ~ -0.3 | 매도 | 제외 권장 |
| < -0.6 | 강한 매도 | 공매도 고려 |

## 출력 형식

```json
{
  "rankings": [
    {
      "rank": 1,
      "ticker": "AAPL",
      "ensemble_score": 0.72,
      "predicted_return": "15.2%",
      "confidence": 78,
      "signal": "bullish",
      "top_bullish": ["warren-buffett-analyst", "charlie-munger-analyst"],
      "top_bearish": [],
      "key_factors": ["강한 ROE (45%)", "안전마진 25%", "일관된 FCF 성장"]
    }
  ],
  "methodology": "17개 투자자 앙상블 + 모멘텀/변동성 조정",
  "period": "3M",
  "analysis_date": "2024-01-15"
}
```

## 사용 예시

### 예시 1: 종목 비교
```
"AAPL, GOOGL, MSFT 중 3개월 후 가장 수익 좋을 종목?"
→ 3개 종목 앙상블 분석 후 순위 반환
```

### 예시 2: 포트폴리오 순위
```
"내 포트폴리오 종목들 수익률 순위 매겨줘: NVDA, TSLA, META, AMZN"
→ 4개 종목 분석 후 순위 및 예상 수익률 반환
```

### 예시 3: 투자 추천
```
"어떤 기술주를 사야 할까?"
→ 주요 기술주 분석 후 상위 추천 종목 반환
```
