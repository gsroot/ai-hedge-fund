# 현재 판단 입력 계약

전체 가상 예시는 [decision_example.json](decision_example.json)이다. 비중은 모두 0~1
분수이며 소수 넷째 자리까지 쓴다. 표시 단위는 0.01%다.

## 실행 정보

- `schema_version`: `portfolio_decision_v1`
- `decision_id`: 영숫자로 시작하는 영숫자/밑줄/하이픈 1~80자. 새 판단은 새 ID.
- `created_at`, `input_cutoff`: timezone 포함 ISO 시각. cutoff는 생성 시각 이하여야 한다.
- `analysis_date`: cutoff의 UTC 날짜. predict, 독립 분석, risk의 날짜와 일치한다.
- `author`: 현재 모델 또는 세션 식별 정보. 임의의 모델명을 추측하지 않는다.
- `base_currency`, `benchmark`: 기준 통화와 비교 ticker. 비교 자산도 assets에 넣는다.
- `previous_decision_id`: 선택 사항. 같은 snapshot root의 이전 추천을 참조한다.

## 사용자 맥락

`user_context`에는 `objective`, `evaluation_horizon`, `spending_horizon`,
`spending_currency`, `risk_tolerance`, `holdings`, `required_amount`를 넣는다.
보유 미상은 `"unknown"`, 알려졌으면 `{ticker:현재 비중}` 객체다. 수량·금액 대신 동일한
전체 자산 기준 비중을 사용한다. CASH를 포함할 수 있으며 합계는 1 이하다. 결과 actions는
보유 대비 add/hold/reduce/exit와 비중 차이를, 미상 보유에는 target_only를 표시한다.
양의 기존 보유는 assets에도 포함해 유지 또는 제외 이유를 명시한다. 미검토 보유를 암묵적으로
전량 매도 대상으로 바꾸지 않는다.
지출 계획이 없다고 확인했으면 spending_horizon은 `"none"`, 필요 금액 미상은 null이다.

`liquidity_min_weight`, `liquidity_basis`(`user_confirmed`/`assumption`),
`liquidity_reason`은 필수다. 지출 가능성이 있는데 금액이 미상이면 준비금 비중을 가정으로
명시한다. 금액이 알려졌으면 `portfolio_value`(기준 통화), `spending_fx_to_base`
(지출 통화 1단위당 기준 통화), `spending_fx_basis`도 넣는다. 최소 준비금이
`required_amount * spending_fx_to_base / portfolio_value`보다 작으면 거절한다.
확인된 사용자 제약을 가정으로 바꾸거나 장기 전략 목표로 덮어쓰지 않는다.

## 출처

`sources` 각 원소: `id`, `provider`, `reference`, `status`, `retrieved_at`.
성공 자료는 `as_of`, `available_at`, `max_age_days`도 필요하며 시각은 timezone을 포함한다.
가격 기준 시각·재무 기준 시각과 공시 가능 시각·조회 시각을 구분한다. 휴일과 공시 주기에
맞는 허용 시차를 명시한다. 허용 시차를 늘려 실패를 숨기지 않는다.

상태는 `ok`, `timeout`, `credentials_missing`, `auth`, `quota`, `stale`, `revision`,
`schema`, `unavailable`. 수정 자료는 `revision_reason`을 쓴다. 대체 원천에는 원래 실패
출처와 fallback 이유도 남긴다. 최신 수정 자료를 과거에 알려진 자료처럼 표기하지 않는다.
필수 가격 실패는 해당 비중의 완료를 막지만 미편입 후보의 실패는 다른 판단을 막지 않는다.

비밀값·인증 query·`.env` 경로를 넣지 않는다. provider 원문을 통째로 복사하지 말고
배포 가능한 사실·출처·기준 시각을 사용한다. 검증기는 출처의 실재나 문장의 진실성을 자동
확인하지 않으므로 작성 시 원자료를 직접 확인한다.

## 자산과 투자 가설

`assets`에는 편입과 검토 후 제외한 대안을 함께 넣는다. 공통 필수는 `ticker`(대문자),
`asset_type`(`stock`/`etf`), `weight`, `calendar`, `selection_reason`,
`quote`(`value`, `currency`, `as_of`, `source_id`)다. 가격과 가격 출처의 as_of는 같다.
실패한 가격은 출처 실패 상태와 null로 기록한다.

양의 비중을 가진 자산에는 `thesis`가 필요하다.

- `facts`: `{text, source_refs:[source ID...]}` 목록. 확인 사실과 추론을 구분한다.
- `rationale`, `price_assumptions`, `downside`, `counterevidence`, `review_trigger`
- `sizing_reason`, `alternative`, `missing_evidence_impact`

기대 수익률 수치는 필수가 아니다. 선택적인 `scenarios`에는 `assumptions`, `calculation`,
`horizon`, `currency`, `return_components`, `target_price`, `source_refs`,
`basis="explicit_assumptions"`를 쓴다. 확률을 쓸 경우 모든 시나리오에 `probability`를 넣어
합계 1로 만들고 `probability_kind="subjective_assumption"`으로 표시한다.
가격 시나리오가 순위나 confidence에서 환산된 값이어서는 안 된다.

주식의 추가 필수 정보는 `issuer`, `sector`다. 직접 보유와 ETF 내부의 같은 발행사를
같은 issuer로 정규화한다. 주식은 predict 전체 rankings에 존재해야 한다.

양의 ETF 비중은 `etf` 객체를 요구한다: `index`, `expense_ratio`(연 보수율), `leverage`,
`diversified`(boolean), `concentration`, `source_id`, `holdings_as_of`, `holdings_complete`,
`holdings:[{ticker, issuer, sector, weight}]`. 구성 기준 시각은 해당 출처와 같아야 한다.
구성 합계는 1 이하이고 complete=true이면 1이다. 현금·기타 노출은 명시적인 식별자·섹터로
남긴다. 부분 구성은 알고 있는 노출과 coverage만 계산한다. 필수 전체 노출 한도가 설정되어
있는데 ETF 구성이 불완전하면 완료를 보류한다.

## 독립 분석

별도 investor JSON은 `{analysis_date, analyses:{TICKER:{INVESTOR:OPINION}}}` 형식이다.
OPINION 예시:

```json
{
  "signal": "bullish",
  "confidence": 70,
  "reasoning": "독립적으로 확인한 사업·가격 근거",
  "data_quality": "complete",
  "analysis_source": "independent_investor_analysis"
}
```

양의 비중인 모든 자산에 요청 관점이 있어야 한다. 자료가 부족한 관점도 실제로 조사한 뒤
`data_quality="insufficient"`와 이유를 남긴다. signal은 bullish/neutral/bearish/abstain,
confidence는 0~100, data_quality는 complete/partial/insufficient다. 누락을 중립으로
만들지 않는다. 부족한 관점이 있어도 최종 thesis가 그 영향을 설명하면 추천할 수 있다.
ETF는 구성·기초자산 평가·비용·집중 위험을 해당 관점에서 분석한다.

## 현금과 제약

`cash`: `weight`, `currency`, `annual_rate`, `liquidity_weight`, `rationale`,
`opportunity_cost`, `liquidity_reason`, `strategic_reason`, `market_regime_reason`.
지출 통화와 다른 현금으로 준비하면 `liquidity_fx_plan`도 쓴다. 시장 규칙과 최종 현금
차이는 허용하며 이유를 설명한다. 현금 0%/100%도 근거와 제약이 허용하면 선택할 수 있다.

`constraints.rationale`은 필수. 기본값은 `max_stock_weight=.15`,
`max_diversified_etf_weight=1`, `max_direct_sector_weight=.35`다.
`asset_caps:{ticker:상한}`으로 개별 제한을 설정한다. 집중/레버리지 ETF에는 이를 명시한다.
`max_total_issuer_weight`, `max_total_sector_weight`는 선택적 전체 노출 한도이며 ETF 내부까지
합산한다. 사용자 한도는 반드시 여기에 반영한다. 기본값을 조정하면 이유와 사용자 제약 준수
여부를 기록한다. 검증기는 비중을 재분배하지 않는다.

## 평가 규칙과 결과

`evaluation`: `method="initial_weights_buy_and_hold"`, 생성 이후의 `review_at`,
`dividends="reinvested"`, `tax_basis="pre_tax"`, `entry_cost_bps`, `exit_cost_bps`,
`fx_cost_bps`, `cost_assumptions`, `review_trigger`. 비용 0도 명시적 근거가 필요하다.
평가 절차는 [evaluation_contract.md](evaluation_contract.md)를 따른다.

출력 status는 ready/conditional/blocked_input/infeasible다. 조건부 추천에는 최종
weights·cash_weight와 가정이 남는다. 입력 오류나 제약 실패에는 검토 원안만 decision에
남고 실행용 weights는 비며 cash_weight는 null이다. JSON·텍스트·엑셀은 같은 결과를 쓴다.
성과 근거는 현재 판단 단계에서 prior_only이며 이후 평가가 관측 결과를 별도로 추가한다.
