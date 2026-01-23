---
name: investor-analysis
description: |
  전설적인 투자자들의 관점으로 주식 분석. Warren Buffett, Charlie Munger, Ben Graham, Cathie Wood,
  Peter Lynch, Phil Fisher, Michael Burry, Bill Ackman, Stanley Druckenmiller, Aswath Damodaran,
  Mohnish Pabrai, Rakesh Jhunjhunwala 등 12명의 투자자 페르소나와 5개의 전문 분석가 제공.
  사용 시점: 투자 분석 요청, "버핏 스타일로 분석", 앙상블 분석, 특정 투자자 관점 분석,
  "AAPL을 분석해줘", "모든 투자자 관점에서 분석"
---

# Investor Analysis Skill

전설적인 투자자 페르소나와 전문 분석가를 활용한 종합 주식 분석 시스템.

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

모든 에이전트는 `src/tools/api.py`의 함수 사용:

| 함수 | 용도 |
|------|------|
| `get_financial_metrics()` | ROE, 마진, 부채비율 등 재무 지표 |
| `search_line_items()` | 상세 재무제표 항목 |
| `get_market_cap()` | 시가총액 |
| `get_prices()` | 가격/거래량 (기술적 분석) |
| `get_insider_trades()` | 내부자 거래 |
| `get_company_news()` | 회사 뉴스 |

사용 예시는 [scripts/data_fetcher.py](scripts/data_fetcher.py) 참조.

## 투자자 프로필

12명의 투자자와 5개의 분석가 프로필:
- **투자자 상세**: [references/investor_personas.md](references/investor_personas.md)
- **분석가 상세**: [references/analyst_personas.md](references/analyst_personas.md)

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

### 예시 1: 버핏 스타일 분석
```
"AAPL을 Warren Buffett 관점으로 분석해줘"
→ warren-buffett-analyst 서브에이전트 호출
```

### 예시 2: 앙상블 분석
```
"테슬라를 모든 투자자 관점에서 분석해줘"
→ 17개 서브에이전트 병렬 호출 후 앙상블 결과 반환
```

### 예시 3: 특정 그룹 분석
```
"NVDA를 가치 투자자들 관점에서 분석해줘"
→ buffett, munger, graham, pabrai 에이전트 호출
```
