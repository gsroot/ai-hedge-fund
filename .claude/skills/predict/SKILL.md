---
name: predict
description: |
  다중 팩터와 투자자 스타일 점수로 주식의 상대 순위를 산정한다. S&P 500,
  NASDAQ 100, KOSPI, KOSDAQ, KRX 및 명시적 티커를 지원한다.
  사용 시점: "$predict", "종목 순위", "상위 종목 분석", "종목 추천",
  "AAPL, MSFT 중 무엇을 우선 조사할까", "S&P 500 분석", "KOSPI 상위 종목".
---

# Predict

현재 데이터로 종목의 상대적 매력도를 점수화하고 순위를 만든다. 출력의
`score_implied_return_pct`는 점수를 읽기 쉬운 범위로 환산한 값일 뿐,
학습·캘리브레이션된 미래 수익률 예측이 아니다. 이를 “예상수익률”이나
“1년 뒤 수익률”로 보고하지 않는다.

## 입력 해석

- 인덱스: `sp500`, `nasdaq100`, `kospi`, `kosdaq`, `kospi200`, `kosdaq150`, `krx`
- 종목: 콤마 구분 `--tickers AAPL,MSFT` 또는 `--tickers 005930,000660`
- 전략: 기본 `hybrid`; 명시 요청 시 `fundamental` 또는 `momentum`
- 분석 대상 수: `--top N`. 인덱스를 시가총액순으로 잘라 실제 분석 수를 제한한다.
- 표시 수: `--display N`. 분석 수는 유지하고 화면 출력만 제한한다.
- 전체 시장을 분석하라는 요청에서는 임의로 `--top`을 넣지 않는다.

## 실행

```bash
# S&P 500 전체 분석, 화면에는 상위 30개
uv run python .agents/skills/predict/scripts/analyze_stocks.py \
  --index sp500 --display 30 --output results.json

# 미국 특정 종목
uv run python .agents/skills/predict/scripts/analyze_stocks.py \
  --tickers AAPL,MSFT,NVDA --output results.json

# KRX 대표 유니버스의 시가총액 상위 50개
uv run python .agents/skills/predict/scripts/analyze_stocks.py \
  --index krx --top 50 --display 20 --output results.json
```

## 점수 구성

- 팩터: 가치, 성장, 품질, 모멘텀, 안전성, 뉴스 심리, 내부자 활동
- 투자자 스타일: Buffett, Lynch, Graham, Fisher, Druckenmiller
- `fundamental`: 투자자 앙상블과 기본 팩터를 결합
- `momentum`: 단·장기 모멘텀, RSI, 추세
- `hybrid`: 펀더멘털과 모멘텀을 조건부 가중 결합
- 현금흐름 품질 게이트: 영업현금흐름·FCF·영업마진 악화 시 감점

## 출력 계약

각 순위 항목은 최소 다음 필드를 포함한다.

```json
{
  "index": "sp500",
  "analysis_date": "YYYY-MM-DD",
  "rankings": [
  {
  "ticker": "AAPL",
  "rank": 1,
  "total_score": 8.2,
  "signal": "strong_buy",
  "score_implied_return_pct": 18.2,
  "return_estimate": {
    "calibrated": false,
    "method": "heuristic_score_mapping",
    "label": "점수 환산값(예상수익률 아님)"
  },
  "data_as_of": "YYYY-MM-DD"
  }
  ]
}
```

`--period`는 현재 `1Y` 라벨만 허용하며 계산 창을 바꾸지 않는다.

## 데이터 시점 규칙

- 프로젝트 루트 `.env`는 데이터 모듈이 자동으로 로드한다. 이미 설정된 프로세스
  환경변수는 `.env` 값으로 덮어쓰지 않는다.
- 일반 `predict`는 오늘 기준 라이브 선별 도구다.
- 미국 Yahoo `Ticker.info`, 뉴스, 내부자 API는 과거 스냅샷이 아니다.
  과거 기준일 분석이나 백테스트에서는 현재 값을 과거 날짜로 캐시하지 않는다.
- 미국 과거 재무 팩터는 [scripts/sec_point_in_time.py](scripts/sec_point_in_time.py)가
  SEC Company Facts를 실제 `filed` 날짜로 거르는 경우에만 허용한다. 이 데이터로
  순위 성과를 검증할 때는 `backtesting`의 `multifactor_walk_forward.py`를 사용한다.
- 한국 DART 연간 재무자료는 기준일 당시 공시되었을 가능성이 높은 최근 사업연도만 사용한다.
- 한국 뉴스는 Naver Search API와 네이버 증권 폴백 모두 발행일을 검증해
  `news_date <= analysis_date`인 기사만 사용한다. 날짜를 검증할 수 없는 기사는 제외한다.
- 인덱스 목록과 시가총액 정렬은 현재 기준이다. 이 결과만으로 과거 초과성과를 주장하지 않는다.
- 데이터가 누락된 종목은 결과에서 빠질 수 있으며, 성공 종목만으로 전체 유니버스 성과를 추론하지 않는다.

## 해석 원칙

1. 순위는 추가 조사 우선순위이지 매수 보장이 아니다.
2. 종목 수익률의 “최대화”를 보장하지 않는다.
3. score와 signal을 기대수익률처럼 사용하지 않는다.
4. 실제 포트폴리오는 독립 투자자 분석, 상관·변동성, 비중 제약, 거래비용을 추가로 검토한다.
5. 전략 성과 주장은 `backtesting`의 point-in-time 검증 결과가 있을 때만 한다.
6. 현금비중은 종목 점수로 정하지 않는다. `portfolio-report`가 출력의 `index`와
   동일 기준일 시장 가격으로 과열·공포·전망을 계산해 별도로 정한다.

## 주요 파일

- [scripts/analyze_stocks.py](scripts/analyze_stocks.py): CLI
- [scripts/analysis.py](scripts/analysis.py): 종합 점수
- [scripts/data_fetcher.py](scripts/data_fetcher.py): 데이터·시점 차단
- [scripts/sec_point_in_time.py](scripts/sec_point_in_time.py): SEC 제출일 기준 재무 스냅샷
- [scripts/reporting.py](scripts/reporting.py): 출력
- [scripts/ranking_algorithm.py](scripts/ranking_algorithm.py): 별도 순위 유틸리티
