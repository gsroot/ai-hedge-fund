---
name: stock-analyzer
description: |
  단일 종목 심층 분석. 재무제표, 기술적 분석, 뉴스 심리, 내부자 거래 종합.
  사용 시점: 특정 종목 분석 요청, 투자 결정 전 심층 조사, "AAPL 분석해줘",
  "테슬라 주식 어때?", 종목 리서치, 기업 분석
---

# Stock Analyzer Skill

단일 종목에 대한 종합적인 심층 분석을 수행하는 시스템.

## 분석 워크플로우

### Step 1: 데이터 수집

`investor-analysis` 스킬의 data_fetcher.py 활용:

```python
from .claude.skills.investor-analysis.scripts.data_fetcher import fetch_all_data

data = fetch_all_data(ticker, end_date)
# 재무 지표, 가격 데이터, 내부자 거래, 뉴스 모두 수집
```

### Step 2: 다차원 분석

5가지 분석 영역을 병렬로 수행:

| 영역 | 서브에이전트 | 분석 내용 |
|------|-------------|----------|
| 펀더멘털 | fundamentals-analyst | 수익성, 성장, 건전성, 밸류에이션 |
| 기술적 | technical-analyst | 추세, 모멘텀, 변동성, 평균회귀 |
| 성장 | growth-analyst | 매출/수익 성장, 마진 확대 |
| 센티먼트 | sentiment-analyst | 내부자 거래 + 뉴스 심리 |
| 뉴스 | news-sentiment-analyst | LLM 기반 뉴스 분석 |

### Step 3: 투자자 관점 분석 (선택)

사용자 요청 시 특정 투자자 관점 추가:

```
"버핏 관점도 포함해서 분석해줘"
→ warren-buffett-analyst 서브에이전트 추가 호출
```

### Step 4: 종합 리포트 생성

모든 분석 결과를 종합하여 투자 리포트 생성.

## 분석 프레임워크

상세 분석 방법론은 [references/analysis_frameworks.md](references/analysis_frameworks.md) 참조.

### 펀더멘털 분석
- 수익성: ROE, ROA, ROIC, 마진
- 성장성: Revenue/EPS CAGR
- 건전성: D/E, Current Ratio, Interest Coverage
- 밸류에이션: P/E, P/B, PEG, FCF Yield

### 기술적 분석
- 추세: 이동평균, 골든/데드크로스
- 모멘텀: RSI, 가격 모멘텀
- 변동성: ATR, 볼린저 밴드
- 통계: Z-Score, Hurst Exponent

### 센티먼트 분석
- 내부자 거래: 매수/매도 비율
- 뉴스 심리: 긍정/부정 비율
- LLM 분석: 헤드라인 심층 분석

## 출력 형식

### 기본 분석 리포트

```json
{
  "ticker": "AAPL",
  "analysis_date": "2024-01-15",
  "summary": {
    "overall_signal": "bullish",
    "confidence": 75,
    "key_strengths": ["강한 수익성", "안정적 현금흐름"],
    "key_risks": ["높은 밸류에이션"],
    "recommendation": "장기 보유 적합"
  },
  "analysis": {
    "fundamentals": {
      "signal": "bullish",
      "confidence": 80,
      "highlights": ["ROE 45%", "FCF Margin 25%"]
    },
    "technical": {
      "signal": "neutral",
      "confidence": 60,
      "highlights": ["50일선 위", "RSI 55"]
    },
    "growth": {
      "signal": "bullish",
      "confidence": 70,
      "highlights": ["매출 성장 8%", "마진 확대 중"]
    },
    "sentiment": {
      "signal": "neutral",
      "confidence": 55,
      "highlights": ["내부자 활동 적음", "뉴스 중립"]
    }
  },
  "valuation": {
    "current_price": 185.50,
    "fair_value_estimate": 200.00,
    "margin_of_safety": "8%"
  }
}
```

### 상세 분석 리포트

투자자 관점 포함 시:

```json
{
  "ticker": "AAPL",
  "investor_perspectives": {
    "warren-buffett-analyst": {
      "signal": "bullish",
      "confidence": 85,
      "reasoning": "강한 moat, 높은 ROE, 적정 안전마진"
    },
    "peter-lynch-analyst": {
      "signal": "neutral",
      "confidence": 65,
      "reasoning": "PEG 2.1로 다소 고평가"
    }
  }
}
```

## 사용 예시

### 예시 1: 기본 분석
```
"AAPL 분석해줘"
→ 5가지 영역 종합 분석 후 리포트 반환
```

### 예시 2: 특정 관점 포함
```
"테슬라를 버핏과 캐시우드 관점에서 분석해줘"
→ 기본 분석 + 2명의 투자자 관점 추가
```

### 예시 3: 투자 결정 지원
```
"NVDA 살까 말까?"
→ 종합 분석 + 명확한 추천 의견 제공
```
