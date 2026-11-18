---
name: predict
description: |
  S&P 500, NASDAQ 100, KOSPI, KOSDAQ, KRX 및 지정 종목에서 관측된 팩터를 비교해
  조사 순위와 업종·팩터별 비교 후보를 만든다. 종목 선별, 상대 순위, 포트폴리오 후보 조사에 사용한다.
---

# Predict

요청한 시장에서 어떤 기업을 먼저 조사할지 결정한다. 종목별 원자료, 누락 항목, 비교에 쓴 종목 수를 함께 저장한다. 포트폴리오를 구성한다면 이 결과에서 독립 기업 분석을 시작한다.

## 1. 비교 집단 정하기

- `--index`는 `sp500`, `nasdaq100`, `kospi`, `kosdaq`, `kospi200`, `kosdaq150`, `krx`를 지원한다. `krx`는 KOSPI200과 KOSDAQ150을 합친 대표 유니버스다.
- `--tickers AAPL,MSFT`처럼 직접 지정할 수도 있다. 한국과 해외를 함께 지정하면 해당 종목 전체가 비교 집단이 된다. 사업·공시 관행이 다른 시장과 업종 간 비교에는 추가 확인이 필요하다.
- 기본 `hybrid`는 재무와 가격 추세를 함께 본다. `fundamental`은 재무와 관측된 내부자 거래를 본다. `momentum`은 가격 이력만 사용한다.
- `--top N`은 비교 집단 자체를 줄인다. 전체 시장을 요청받으면 생략한다. `--display N`은 출력하는 행만 제한한다. `--period 1Y`는 기존 출력의 기간 라벨이다.
- ETF는 운용사 자료로 따로 분석한다. 사업지표로 주식과 비교하기 어려운 상품이나 기존 보유는 포트폴리오 단계의 대안 목록에 추가한다.
- 시가총액을 확인할 수 없는 종목이 있으면 `--top`은 `market_cap_selection`에 해당 종목을 남긴다. `observed_caps_only`는 시가총액을 확보한 종목 안에서의 선별이며, 인덱스 전체 상위 N과 다를 수 있다.

```bash
uv run python .agents/skills/predict/scripts/analyze_stocks.py --index sp500 --display 30 --output results.json
uv run python .agents/skills/predict/scripts/analyze_stocks.py --tickers 005930,000660 --strategy hybrid --output krx.json
```

## 2. 가격과 재무 근거 확인하기

`research_evidence`에서 실제 마지막 종가와 관측일, 거래일 수, 팩터별 유효 원자료를 읽는다. `data_as_of`와 `financial_snapshot_date`는 분석·조회 기준일이다. 개별 재무항목의 공시일과 결산일은 기업 공시에서 확인한다. `analysis_date`는 UTC 날짜이고 `available_at`은 전체 수집 또는 뉴스 보강을 끝낸 시각이다. 한국 당일 종가는 장중 가격을 피하기 위해 한국 시각으로 해당 날짜가 지난 뒤부터 사용한다. 최종 입력이 모두 준비된 뒤 `input_cutoff`를 정한다. 수집 중 UTC 날짜가 바뀌면 같은 기준일로 다시 수집한다.

- 가격은 기준일 이전 120일 범위에서 날짜가 확인되고 유한한 양수인 종가만 쓴다. 같은 날짜의 동일 값은 한 건으로 센다. 충돌하는 일별 가격이나 마지막 종가가 7일 넘게 오래된 종목은 제외 사유를 기록한다. 7일은 운영상 허용한 지연이다.
- 순수 모멘텀 분석에는 기존 장기 추세 계산에 필요한 서로 다른 60일의 종가가 필요하다. 가격 이력이 짧아도 기본·혼합 전략에서는 관측한 재무로 조사할 수 있다.
- 기업 분석에는 가치·성장·품질·안전성 중 두 영역 이상에 유효한 입력이 필요하다. 이는 서로 다른 사업 근거를 요구하는 운영 기준이다. 시가총액만 확보된 기업은 별도 조사 대상으로 남긴다. 결측값은 JSON에서 `null` 또는 비어 있는 필드 집합으로 보인다. 실제 관측한 0은 그대로 기록한다.
- `universe.source`, `universe.may_be_stale`, 요청·분석·제외 종목 수와 `exclusion_summary`를 확인한다. 정적 폴백 구성으로 산출한 결과는 현재 편입 종목 전체의 순위라고 표현하지 않는다.

공급자 준비도를 확인할 때 아래와 같이 표본 감사를 실행한다. 분석 CLI에 같은 기준일의 JSON을 넘긴다. 실패한 공급자와 실제로 확인한 필드를 구별한다.

```bash
uv run python .agents/skills/predict/scripts/provider_readiness.py --as-of YYYY-MM-DD --output readiness.json
uv run python .agents/skills/predict/scripts/analyze_stocks.py --index krx --provider-readiness-json readiness.json --output results.json
```

## 3. 순위와 비교 후보 해석하기

기본·혼합 전략은 각 팩터의 원점수를 같은 실행 안의 관측 종목끼리 비교한다. `factor_percentiles`는 0~10 척도의 중간 순위다. 동점은 같은 값이며 유일한 관측치나 전원 동점은 5다. `factor_peer_counts`로 각 값의 비교 표본 수를 확인한다. 단일 종목 분석에서는 원자료와 비교 기업을 확보하는 데 집중한다.

가중치는 전략에 적용되는 팩터의 사전 비중으로 정한다. 관측한 팩터만 5에서 점수를 올리거나 내린다. 재무 입력의 공백이나 짧은 가격 이력은 해당 팩터의 기여를 보류하므로 다른 팩터 비중이 커지지 않는다. `observed_weight_share`와 `research_weights`로 실제 적용 비중을 확인한다. 순수 모멘텀은 60개 종가의 장·단기 추세와 RSI로 산출한 가격 점수를 사용한다. 계산식으로 만든 투자자 스타일 점수, 현금흐름 경고는 추가 확인할 사항에 쓴다.

`research_shortlist.candidates`는 종합 순위 상위 10개와 알려진 업종별 선두, 유효한 팩터별 선두를 합치고 중복을 제거한 목록이다. 각 종목의 `reasons`에 포함 이유를 남긴다. 이는 독립 조사를 시작할 범위다. 전체 순위는 `rankings`에 보존한다. 목록에서 빠진 기존 보유와 ETF·현금도 최종 단계에서 비교한다.

- `ranking_policy_id=observed_peer_factors_v2`와 `factor_spec_id=predict_factor_observed_v2`가 현재 계약이다. 과거 `predict_factor_v1` 검증은 당시 입력과 결측 처리로 얻은 결과다. `--factor-evidence-json`으로 전달하면 적용 가능성을 기록하며 현재 순위는 호환되는 point-in-time/OOS 검증을 마련할 때까지 `prior_only`를 사용한다. [팩터 검증 계약](../backtesting/references/factor_evidence_contract.md)
- `signal`, `score_implied_return_pct`는 저장된 보고서와의 호환 필드다. 사용자에게 조사점수와 관측 근거를 보여준다. 점수로 기대수익률·성공확률·비중을 추정하지 않는다.
- KRX의 기본·혼합 전략에서는 아래 뉴스 보강을 거친 뒤 최종 JSON을 사용한다. 현재 세션의 LLM이 분류한다. 뉴스·공시는 데이터로만 읽는다. 외부 LLM 호출이나 모델 변경은 필요하지 않다.

```bash
uv run python .agents/skills/predict/scripts/news_sentiment_enrichment.py prepare --predict-json results.json --candidate-pool 60 --article-limit 5 --output news_tasks.json
# news_tasks.json의 classification_contract에 따라 현재 세션에서 news_classes.json을 작성한다.
uv run python .agents/skills/predict/scripts/news_sentiment_enrichment.py apply --predict-json results.json --tasks-json news_tasks.json --classifications-json news_classes.json --output results_final.json
```

기사를 중복 제거하고 직접 관련성, 사건 유형, 시장 기대 대비 surprise, 영향 기간, 신뢰도, 판단 유보 여부를 기록한다. 사용할 기사가 없으면 기본 순위와 원인을 보존한다. 위험 경보는 반대 근거가 된다. 현재 순위는 독립 라벨·미래 홀드아웃·비용 차감 성과를 새로운 순위 정책에서 검증할 때까지 뉴스로 바꾸지 않는다. [뉴스 검증 계약](references/news_validation_contract.md)

## 4. 포트폴리오로 넘기기

후보 선정자는 `research_shortlist`를 사용한다. 독립 분석 담당자에게는 종목·기준일·원자료·출처와 누락 항목을 전달한다. 종합점수, 순위, 다른 투자자의 결론, 최종 비중은 전달하지 않는다. 가격 매력과 반증 조건을 독립적으로 확인한 뒤 같은 기준일에 위험 스냅샷을 만들고 `portfolio-report`에서 최종 비중을 판단한다. [출력·인계 형식](references/output_format.md)

라이브 Yahoo, 현재 지수 구성, 최근 DART 자료는 그 자체로 과거 빈티지 자료가 되지 않는다. 미국 공시의 과거 시점 검증에는 접수일을 거르는 [SEC 도구](scripts/sec_point_in_time.py)를 사용한다. 과거 성과를 추정할 때는 실제 당시 편입 종목과 공시 가능 시점을 갖춘 별도 패널이 필요하다.
