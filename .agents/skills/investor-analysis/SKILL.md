---
name: investor-analysis
description: |
  전설적인 투자자들의 관점으로 주식 분석. Warren Buffett, Charlie Munger, Ben Graham, Cathie Wood,
  Peter Lynch, Phil Fisher, Michael Burry, Bill Ackman, Stanley Druckenmiller, Aswath Damodaran,
  Mohnish Pabrai, Rakesh Jhunjhunwala 등 12명의 투자자 페르소나와 5개의 전문 분석가 제공.
  사용 시점: 투자 분석 요청, "버핏 스타일로 분석", 앙상블 분석, 특정 투자자 관점 분석,
  "AAPL을 분석해줘", "모든 투자자 관점에서 분석"
  단일 종목 심층 분석: "AAPL 분석해줘", "테슬라 주식 어때?", "NVDA 살까 말까?"
  한국 종목 지원: "삼성전자 분석해줘", "005930 버핏 스타일로 분석", "SK하이닉스 앙상블 분석"
---

# Investor Analysis Skill

전설적인 투자자 페르소나와 전문 분석가를 활용한 종합 주식 분석 시스템.
단일 종목 심층 분석부터 앙상블 분석까지 지원합니다.
한국 종목(6자리 숫자 코드)은 자동으로 DART + PyKRX로 라우팅됩니다.

## 분석 모드

### 모드 1: 빠른 분석 (기본)

"AAPL 분석해줘", "테슬라 주식 어때?", "삼성전자 분석해줘" 같은 일반 분석 요청 시:

```
5개 전문 분석가 자동 호출 (병렬):
- fundamentals-analyst: 수익성, 성장, 건전성, 밸류에이션
- technical-analyst: 추세, 모멘텀, 변동성, 평균회귀
- growth-analyst: 매출/수익 성장, 마진 확대
- sentiment-analyst: 내부자 거래 + 뉴스 심리
- news-sentiment-analyst: LLM 기반 뉴스 분석
```

### 모드 2: 투자자 관점 분석

"버핏 스타일로 분석해줘" 같은 특정 투자자 요청 시:

```
해당 투자자 에이전트 호출 (예: warren-buffett-analyst)
```

### 모드 3: 앙상블 분석

"모든 투자자 관점에서 분석해줘" 요청 시:

```
17개 서브에이전트 병렬 호출 → 가중 평균 계산 → 종합 신호
```

### 모드 4: 리포트 모드

"종합 리포트 만들어줘", "투자 리포트" 요청 시:

```
5개 분석가 + 선택적 투자자 관점 → 구조화된 리포트 생성
```

---

## 워크플로우

### 1. 투자자/분석가 선택

사용자 요청에 따라 적절한 서브에이전트 선택:

| 키워드 | 서브에이전트 |
|--------|-------------|
| "버핏", "가치 투자", "moat" | warren-buffett-analyst |
| "멍거", "정신 모형" | charlie-munger-analyst |
| "그레이엄", "딥 밸류", "NCAV" | ben-graham-analyst |
| "캐시 우드", "혁신", "ARK" | cathie-wood-analyst |
| "린치", "PEG", "10배주" | peter-lynch-analyst |
| "피셔", "성장주" | phil-fisher-analyst |
| "버리", "역발상" | michael-burry-analyst |
| "액만", "행동주의" | bill-ackman-analyst |
| "드러켄밀러", "모멘텀" | stanley-druckenmiller-analyst |
| "다모다란", "DCF" | aswath-damodaran-analyst |
| "파브라이", "단도" | mohnish-pabrai-analyst |
| "준준왈라", "신흥시장" | rakesh-jhunjhunwala-analyst |
| "기술적 분석", "차트" | technical-analyst |
| "펀더멘털", "재무분석" | fundamentals-analyst |
| "성장 분석" | growth-analyst |
| "센티먼트", "심리" | sentiment-analyst |
| "뉴스 분석" | news-sentiment-analyst |

### 2. 단일 투자자 분석

특정 투자자 요청 시:

```
1. Task 도구로 해당 서브에이전트 호출
2. 서브에이전트가 분석 수행
3. 결과 반환: {signal, confidence, reasoning}
```

예시:
```python
Task(
    subagent_type="warren-buffett-analyst",
    prompt="AAPL 종목을 분석해주세요. 현재 날짜: 2024-01-15"
)
```

### 3. 앙상블 분석

"모든 투자자", "종합 분석" 요청 시:

```
1. 17개 서브에이전트 병렬 호출
2. 각 에이전트 신호 수집
3. scripts/ensemble_analyzer.py로 가중 평균 계산
4. 최종 신호 및 순위 반환
```

## 데이터 수집

모든 에이전트는 `scripts/data_fetcher.py`의 함수 사용:

| 함수 | 용도 | 해외 소스 | 한국 소스 |
|------|------|-----------|-----------|
| `get_financial_metrics()` | ROE, 마진, 부채비율 등 | Yahoo Finance | DART + PyKRX |
| `search_line_items()` | 상세 재무제표 항목 | Yahoo Finance | DART 재무제표 |
| `get_market_cap()` | 시가총액 | Yahoo Finance | KRX API / PyKRX |
| `get_prices()` | 가격/거래량 (기술적 분석) | Yahoo Finance | FDR / PyKRX |
| `get_insider_trades()` | 내부자 거래 | Yahoo Finance | DART 주요주주 공시 |
| `get_company_news()` | 회사 뉴스 | Yahoo Finance | 네이버 뉴스 / DART |

해외 종목은 무료 (API 키 불필요). 한국 종목은 `DART_API_KEY` 환경변수 필요.
6자리 숫자 종목코드 입력 시 자동으로 한국 데이터소스로 라우팅됩니다.

## 참고 자료

### 투자자/분석가 프로필
- **투자자 상세**: [references/investor_personas.md](references/investor_personas.md)
- **분석가 상세**: [references/analyst_personas.md](references/analyst_personas.md)

### 분석 프레임워크
- **종목 분석 방법론**: [references/analysis_frameworks.md](references/analysis_frameworks.md)
  - 펀더멘털 분석 (수익성, 성장성, 건전성, 밸류에이션)
  - 기술적 분석 (추세, 모멘텀, 변동성)
  - 성장 분석 (매출 품질, 마진 확대)
  - 센티먼트 분석 (내부자 거래, 뉴스 심리)
  - 밸류에이션 프레임워크 (DCF, 상대가치, 안전마진)

## 신호 출력 형식

모든 에이전트는 동일한 형식으로 반환:

```json
{
  "signal": "bullish|bearish|neutral",
  "confidence": 0-100,
  "reasoning": "분석 근거 설명"
}
```

## 앙상블 가중치

투자자별 기본 가중치 (역사적 성과 기반):

| 투자자 | 가중치 | 전문 분야 |
|--------|--------|----------|
| Warren Buffett | 1.0 | 가치 투자, 경제해자 |
| Charlie Munger | 0.95 | 정신 모형, ROIC |
| Aswath Damodaran | 0.90 | DCF 밸류에이션 |
| Peter Lynch | 0.85 | GARP, PEG |
| Ben Graham | 0.85 | 딥 밸류, 안전마진 |
| Stanley Druckenmiller | 0.80 | 매크로, 모멘텀 |
| Michael Burry | 0.75 | 역발상, 자산가치 |
| Cathie Wood | 0.70 | 파괴적 혁신 |

앙상블 계산은 [scripts/ensemble_analyzer.py](scripts/ensemble_analyzer.py) 참조.

## 사용 예시

### 예시 1: 빠른 분석 (기본)
```
"AAPL 분석해줘"
"테슬라 주식 어때?"
"NVDA 살까 말까?"
→ 5개 전문 분석가 병렬 호출 후 종합 결과 반환
```

### 예시 2: 버핏 스타일 분석
```
"AAPL을 Warren Buffett 관점으로 분석해줘"
→ warren-buffett-analyst 서브에이전트 호출
```

### 예시 3: 앙상블 분석
```
"테슬라를 모든 투자자 관점에서 분석해줘"
→ 17개 서브에이전트 병렬 호출 후 앙상블 결과 반환
```

### 예시 4: 특정 그룹 분석
```
"NVDA를 가치 투자자들 관점에서 분석해줘"
→ buffett, munger, graham, pabrai 에이전트 호출
```

### 예시 5: 투자 리포트 생성
```
"AAPL 종합 투자 리포트 만들어줘"
"마이크로소프트 버핏, 린치 관점 포함해서 리포트"
→ 구조화된 리포트 형식으로 반환
```

### 예시 6: 한국 종목 분석
```
"삼성전자 분석해줘"
"005930 버핏 스타일로 분석해줘"
→ 6자리 종목코드 자동 감지 → DART + PyKRX 데이터 사용
```

### 예시 7: 한국 종목 앙상블 분석
```
"SK하이닉스를 모든 투자자 관점에서 분석해줘"
→ 17개 서브에이전트 병렬 호출 (DART/PyKRX 데이터 자동 사용)
```

---

## 리포트 출력 형식

리포트 모드 또는 상세 분석 요청 시 아래 형식으로 반환:

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

### 투자자 관점 포함 리포트

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
