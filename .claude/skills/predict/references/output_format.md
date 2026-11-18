# 조사 결과와 독립 분석 인계

첫 문단에 분석일, 요청한 비교 집단, 실제로 분석한 수, 제외 원인, 유니버스 출처와 데이터 지연을 적는다. 결과표에는 순위·종목·조사점수·가격 관측일·재무 근거 수·관측 비중을 표시한다. 기업이 실제 포트폴리오에 들어갈지는 독립 분석과 가격·위험 비교에서 판단한다.

| JSON | 쓰임 |
|---|---|
| `rankings`, `excluded` | 전체 순위와 제외 사유를 대조한다. |
| `research_shortlist.candidates[].ticker/rank/reasons` | 종합 상위, 업종 선두, 팩터 선두가 어디서 겹치는지 확인한다. |
| `research_evidence.price_start/price_end/last_close/price_observations` | 관측 가능한 일별 종가의 범위와 실제 마지막 값을 확인한다. 원자료 통화·조정 기준은 별도 확인한다. |
| `research_evidence.fundamental_fields`, `cash_flow_observations` | 관측한 값으로 독립 기업 분석을 시작한다. 다른 보고서의 인용 날짜와 원 단위를 확인한다. |
| `research_evidence.last_price_providers`, `financial_provider`, `pe_basis` | 식별 가능한 실제 종가·재무 공급자와 후행·선행 P/E 구분을 읽는다. 빈 값이면 원천을 확인한다. |
| `rank_inputs`, `factor_peer_counts`, `factor_percentiles`, `research_weights` | 팩터 원점수, 관측 비교 종목 수, 중간 순위와 영향력을 재현한다. |
| `observed_weight_share` | 현재 증거가 담당한 순위 가중치 합계다. 뉴스에 예약된 몫과 자료가 없는 팩터는 포함하지 않는다. |
| `factor_weight_policy`, `provider_readiness_policy` | 검증 상태와 자료의 한계를 확인한다. |

독립 분석 담당자에게는 원자료만 전달한다. 후보 선정 사유, 팩터 등수, 투자자 스타일 점수와 다른 담당자의 의견은 후보를 고른 사람이 보관한다. 첫 번째 기업 가설, 불리한 시나리오, 현재 가격에서 무엇이 이미 반영되었는지 각자 작성한 뒤 결과를 모은다.
