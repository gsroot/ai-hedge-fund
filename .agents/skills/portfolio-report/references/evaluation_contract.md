# 구성 이후 평가 계약

추천 스냅샷과 `decision_prices_v1` 가격 JSON을 사용한다. 첫 범위는 같은 거래소 달력의
자산을 최초 비중으로 매수 후 보유하는 평가다. 매일 비중을 재조정하지 않는다.
여러 추천을 계속 따라 매매한 전략 전체의 실적은 별도 구현 없이는 주장하지 않는다.

시작은 추천 생성 시각과 입력 cutoff 중 늦은 시각 이후의 첫 정규장 시가다.
종료는 고정된 review_at 이전 또는 같은 마지막 정규장 종가다. 리뷰 시각 이전에는
not_due, 필요한 관측이 없으면 incomplete다. 중간 점검은 원본을 수정하지 말고 가설 변화와
새 추천으로 별도 기록한다.

## 가격 JSON

최상위: `schema_version="decision_prices_v1"`, `as_of`(timezone 포함 관측 확정 시각),
`calendar`, `series`, 선택적인 `fx`, `thesis_reviews`.

calendar에는 `id`(추천과 같은 XNYS 등), `provider`, `reference`, `coverage_start`,
`coverage_end`, `sessions:[{date:"YYYY-MM-DD", open_at:ISO시각, close_at:ISO시각}]`를 쓴다.
범위는 생성부터 평가일까지 포괄하며 실제 거래일을 순서대로 넣는다. 공휴일·임시 휴장·단축
거래도 원천으로 확인한다. 달력 날짜로 거래일을 추정하거나 누락된 거래일을 건너뛰지 않는다.
달력의 완전성은 원천으로 확인한다. 검증기는 순서·중복·범위를 검사한다.

series는 ticker별 객체다. `currency`, `calendar`, `provider`, `reference`, `retrieved_at`,
`price_basis="total_return_adjusted"`, `bars:[{date,open,close,status:"ok"}]`를 넣는다.
상장폐지·거래 정지·timeout 등은 해당 상태로 남기며 임의 가격을 보간하지 않는다.
비교 ETF를 포함해 기간 내 모든 거래일의 가격이 있어야 한다.

초기 경로는 **배당 재투자·분할을 반영한 총수익 조정 OHLC**만 받는다. provider가
일관된 raw OHLC와 adjusted close를 제공하면 같은 날의 adjusted_close/raw_close로
open과 close를 모두 조정하고 변환·출처를 기록한다. 조정 가격에 배당을 다시 더하지 않는다.
ETF 보수는 NAV 총수익에 이미 반영되므로 다시 차감하지 않는다.

기준 통화와 다른 통화마다 `fx[통화]`에 `currency`, `base_currency`, `provider`,
`reference`, `retrieved_at`, `bars:[{date,open,close}]`를 넣는다. 환율은 **외화 1단위당
기준 통화**다. 동일 통화만 자동 1이며 미상 환율은 1로 처리하지 않는다.

## 수익과 비용

초기 예산은 최초 비중이며 그 안에서 진입 비용을 지불한다. 취득 수량의 가치는
weight/(1+entry_cost)이고 종료 평가에 exit_cost를 차감한다. 외화는 진입·종료에 환전
비용도 반영한다. 비교 ETF에도 같은 규칙을 쓴다. 연구용 소수 수량 가정이며 실제 주문을
생성하지 않는다. 현금은 실제 경과 초/365.25일과 명시적 연이율로 복리 계산한다.
외화 현금은 환율과 환전 비용을 반영한다. 현금 이자는 가정 경로이며 실제 계좌 실적이 아니다.
첫 구현은 세전 기준이다.

출력: portfolio_return, benchmark_return, 단순 차이 relative_return, 자산별/CASH
contributions, 관측 기간 MDD·변동성·NAV. 짧은 표본을 표시하고 미래 알파로 해석하지 않는다.

## 사업 가설과 버전

`thesis_reviews[ticker]`는 `{status,reasoning,as_of,sources}`다.
status는 intact/contradicted/uncertain, 미작성은 not_reviewed다. sources는 현재 확인한
자료 참조 목록이다. 주가 하락과 사업 가설 붕괴를 자동으로 동일시하지 않는다.

`--reason`에 최초 평가 또는 수정 이유를 쓰면 원본 추천을 보존하면서
evaluations/000001.json부터 새 버전을 생성한다. 손실·자료 실패·미도래 결과도 남는다.
추천 hash가 다르면 평가를 거절한다. 수정 데이터는 새 data hash와 평가 버전으로 보존한다.
자동 스케줄이나 외부 게시를 생성하지 않는다.
