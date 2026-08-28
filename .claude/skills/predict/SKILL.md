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

## 팩터 근거 기반 가중치

7개 기본 팩터는 모두 같은 point-in-time OOS 기준으로 판정한다. 검증
JSON이 없으면 기존 prior 상대 비중을 유지하지만 `prior_only`·`unvalidated`를
결과에 명시한다. 적용 가능한 JSON이 있으면 검증 기간, 시장, 인덱스,
시점 계약을 검사하고 원시 metrics에서 등급을 다시 계산해 prior를 수축한다.

```bash
uv run python .agents/skills/predict/scripts/analyze_stocks.py \
  --index krx --factor-evidence-json artifacts/krx_predict_factor_evidence.json \
  --display 30 --output krx_base.json
```

- 등급은 `contradicted`, `weak`, `unvalidated`, `preliminary`, `promising`,
  `robust`이며 multiplier는 각각 0, 0.35, 0.50, 0.65, 0.85, 1.0이다.
- multiplier를 prior에 곱한 후 기존 팩터 블록 총량으로 정규화한다. 근거가
  약한 팩터의 상대 비중은 줄고 강한 팩터로 이동한다.
- 검증 종료일은 분석일보다 앞서야 하며 다른 시장·인덱스 근거는 거부한다.
- 팩터 정의와 산출 계약이 다른 기존 backtest JSON은 적용하지 않는다.
- 산출물은 기본 팩터 블록만 검증한다. 투자자 persona, GARP 보너스,
  현금흐름 패널티, enhanced momentum/hybrid 결합까지 전체 모델이 검증된
  것으로 표현하지 않는다.
- 검증 JSON은 `backtesting` 스킬의
  `references/factor_evidence_contract.md`와 `scripts/factor_evidence.py`로 생성한다.

## Provider 준비도 증거

순위 전에 KRX와 S&P provider의 자격 증명 이름, 표본 응답, 필수 필드, as-of,
revision과 quota 상태를 감사한다. key 값은 산출물에 포함하지 않는다.

```bash
uv run python .agents/skills/predict/scripts/provider_readiness.py \
  --as-of YYYY-MM-DD \
  --output artifacts/evidence/provider_readiness_YYYYMMDD.json

uv run python .agents/skills/predict/scripts/analyze_stocks.py \
  --index krx \
  --provider-readiness-json artifacts/evidence/provider_readiness_YYYYMMDD.json \
  --output results.json
```

- credential missing, auth, timeout, quota, schema, empty, stale, unavailable을 서로 다른
  상태로 기록하며 실제 팩터 값 0으로 바꾸지 않는다.
- 표본이 모두 성공해도 current universe·metadata·수정 가격을 historical membership이나
  재무 vintage 근거로 승격하지 않는다.
- snapshot이 없거나 적용 provider가 실패하면 `provider_readiness_policy`를
  `missing_evidence_requires_prior_or_explanation_only`로 직렬화한다.

## 현재 LLM 뉴스 분석

KRX의 `fundamental` 또는 `hybrid` 분석은 기본 정량 순위를 만든 뒤 상위 후보의
뉴스를 현재 스킬 LLM으로 분류한다. 독립 검증 전에는 뉴스가 순위에 영향을 주지 않고
위험 경보와 설명 evidence로만 남는다. 전체 시장 요청에서는 1차 분석에 임의의
`--top`을 넣지 않고, 뉴스 분석 후보군만 기본 60개로 제한한다.

```bash
# 1. 전체 유니버스 기본 순위
uv run python .agents/skills/predict/scripts/analyze_stocks.py \
  --index krx --output krx_base.json

# 2. 기본 순위 상위 60개의 최근 뉴스 분류 작업 생성
uv run python .agents/skills/predict/scripts/news_sentiment_enrichment.py prepare \
  --predict-json krx_base.json --candidate-pool 60 --article-limit 5 \
  --output krx_news_tasks.json

# 3. 현재 스킬 LLM이 중복 제거된 작업을 직접 분류해 아래 계약으로 저장
# {"schema_version":2,"classifier_policy_id":"news_event_v2",
#  "analysis_date":"YYYY-MM-DD","source":"active_skill_llm",
#  "results":[{"ticker":"005930","classifications":[
#    {"article_index":0,"relevance":"relevant|unrelated|ambiguous",
#     "event_type":"earnings_surprise|guidance|contract|financing_dilution|...",
#     "sentiment":"positive|negative|neutral",
#     "surprise":"positive|negative|none|unknown",
#     "impact_horizon":"intraday|short|medium|long|none",
#     "confidence":0-100,"abstain":false,"reasoning":"..."}]}]}

# 4. 기본 실행: 분류 evidence와 위험 경보만 추가하고 순위는 유지
uv run python .agents/skills/predict/scripts/news_sentiment_enrichment.py apply \
  --predict-json krx_base.json --tasks-json krx_news_tasks.json \
  --classifications-json krx_news_classifications.json \
  --output krx_final.json

# 5. 모든 독립 검증 게이트를 통과한 산출물이 있을 때만 뉴스 점수와 재순위를 허용
uv run python .agents/skills/predict/scripts/news_sentiment_enrichment.py apply \
  --predict-json krx_base.json --tasks-json krx_news_tasks.json \
  --classifications-json krx_news_classifications.json \
  --validation-json news_sentiment_validation.json \
  --output krx_final.json
```

- 현재 작업에 선택된 LLM과 추론 설정을 그대로 사용한다. 외부 LLM API를 호출하거나
  모델명을 지정하지 않는다.
- 링크 또는 정규화 제목이 같은 기사를 분류 전에 제거한다.
- 종목 관련성을 먼저 확인하고 이벤트 유형, 기대 대비 surprise, 영향 기간을 분리한다.
- 무관·애매·abstain·60% 미만 신뢰도와 `market_price_recap`,
  `routine_disclosure`는 의사결정 evidence에서 제외한다.
- 70% 이상 신뢰도의 부정 이벤트는 감점 대신 `risk_flags`에 남긴다.
- 기본 keyword sentiment도 중립 5점으로 고정해 상대 순위 영향을 없애고 원점수는
  `sentiment_diagnostics`에 보존한다.
- 독립 사람 라벨의 의미 정확도, 미래 홀드아웃 방향성, 비용 차감 포트폴리오 개선을
  모두 통과한 `schema_version: 2` 검증 산출물이 있을 때만 factor evidence로
  결정된 sentiment 비중을 LLM 점수에 적용한다. `accuracy_validated: true`만 단독으로
  적은 파일은 거부한다.
- 뉴스 순위 반영은 위 공통 factor evidence와 이 분류·성과 전용 게이트를
  모두 통과해야 한다.
- 검증 JSON을 만들거나 판정할 때는
  [references/news_validation_contract.md](references/news_validation_contract.md)를 읽는다.
- 분류 confidence와 actionable coverage를 곱해 중립 5점으로 수축하고 2~8점으로 제한한다.
- 검증되지 않은 ticker·article index·분류 필드는 제외한다.
- 분류가 없는 후보는 중립 sentiment를 유지한다.
- `momentum` 전략은 sentiment를 사용하지 않으므로 이 단계를 실행하지 않는다.
- 최종 JSON에 분류 evidence, 적용 정책, 검증 게이트 실패 사유를 남긴다. 실제 정확도나
  성과 향상은 별도 point-in-time 검증 전까지 주장하지 않는다.

## 점수 구성

- 팩터: 가치, 성장, 품질, 모멘텀, 안전성, 뉴스 심리, 내부자 활동
- 뉴스 심리: 검증 전에는 중립값과 진단 evidence만 사용하고, 전체 검증 통과 후에만
  KRX 상위 후보의 현재 LLM 이벤트 분류로 교체
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
  "factor_weights": {
    "value": 0.25, "growth": 0.20, "quality": 0.20,
    "momentum": 0.10, "safety": 0.10, "sentiment": 0.08, "insider": 0.07
  },
  "factor_weight_policy": {
    "factor_spec_id": "predict_factor_v1",
    "mode": "prior_only|evidence_shrunk"
  },
  "provider_readiness_policy": {
    "contract_id": "provider_readiness_v1",
    "mode": "not_provided|sampled",
    "all_samples_ready": false,
    "ranking_policy": "missing_evidence_requires_prior_or_explanation_only"
  },
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
- [scripts/factor_evidence.py](scripts/factor_evidence.py): 팩터 근거 검증·수축 정책
- [scripts/provider_readiness.py](scripts/provider_readiness.py): provider 인벤토리·실제 표본·실패 상태
- [scripts/data_fetcher.py](scripts/data_fetcher.py): 데이터·시점 차단
- [scripts/sec_point_in_time.py](scripts/sec_point_in_time.py): SEC 제출일 기준 재무 스냅샷
- [scripts/news_sentiment_enrichment.py](scripts/news_sentiment_enrichment.py): 상위 후보 뉴스 작업·검증·재순위
- [scripts/reporting.py](scripts/reporting.py): 출력
- [scripts/ranking_algorithm.py](scripts/ranking_algorithm.py): 별도 순위 유틸리티
