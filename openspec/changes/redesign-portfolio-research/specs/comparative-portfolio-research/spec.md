## Purpose

전략에 맞춰 조사한 후보를 사용자 제약 아래에서 실제 배분 대안으로 비교하고, 결정 당시의 자료와 이후 관측을 분리하여 어떤 선택이 가치를 더했는지 확인한다.

## ADDED Requirements

### Requirement: Strategy-specific research evidence
시스템은 전략별 관측 입력, 누락 사유, 기준일과 재현 가능한 조사 후보를 제공해야 한다(SHALL).

#### Scenario: Price-only momentum
- **WHEN** 재무 응답이 없어도 해당 전략을 계산할 가격 이력이 충분하다.
- **THEN** 재무 결측을 이유로 모멘텀 순위를 버리거나 재무 감점을 부과하지 않는다.

#### Scenario: Incomplete coverage and ties
- **WHEN** 일부 가격·재무 근거가 없거나 서로 다른 종목이 동점이다.
- **THEN** 누락을 추적하고 동일한 입력에서 완료 순서에 무관하게 동일한 순위와 조사 목록을 얻는다. 금융 데이터 실패와 뉴스·팩터의 표본 외 검증 상태는 유지한다.

### Requirement: Comparable historical risk
시스템은 포트폴리오별 과거 하방을 동일한 날짜와 기준 통화의 관측에서 계산해야 한다(SHALL).

#### Scenario: Missing market or currency series
- **WHEN** 일부 대안에 필요한 가격이나 환율이 없거나 오래되었다.
- **THEN** 해당 대안의 미산출 사유를 기록하고, 자료가 있는 자산·대안의 관측을 보존한다.

### Requirement: Frozen comparable allocations
시스템은 선택안, 준비금을 포함한 기준안, 현금안, 기존 보유안의 비중·비용 산출 가능 여부·선택 근거를 검증하고 직렬화해야 한다(SHALL).

#### Scenario: Partial starting holdings
- **WHEN** 사용자 보유가 미상이거나 합계가 전체 금액에 미치지 못한다.
- **THEN** 보유 유지안과 전환 비용의 한계를 표시하고 선택 가능한 목표 비중은 제시한다.

#### Scenario: Constraints and adverse assumptions
- **WHEN** ETF 내부 노출이나 자금 사용 조건이 대안의 한도를 초과하거나 하방 가정이 달라진다.
- **THEN** 대안의 위반과 조건을 드러내고 동일한 비교를 보고서와 추천 스냅샷에 남긴다.

### Requirement: Prospective comparison
시스템은 추천 시점에 고정한 대안을 같은 사후 기간·통화·비용 규칙으로 평가해야 한다(SHALL). 기존 스냅샷은 계속 재현할 수 있어야 한다.

#### Scenario: An alternative has a missing price
- **WHEN** 선택안과 기준 ETF의 평가가 가능하지만 기존 보유 종목의 사후 가격이 누락된다.
- **THEN** 가능한 실현 모의 수익과 미평가 대안의 사유를 함께 남긴다. 누락된 종목의 수익을 0으로 추정하지 않는다.

#### Scenario: Current balance known
- **WHEN** 최초 비중 전체와 추정 전환 비용이 고정되어 있다.
- **THEN** 처음부터 새 자금을 투입하는 비교와 기존 보유에서 전환하는 비교의 비용 가정을 구분하고 나중에 선택된 대안만 남도록 결과를 걸러내지 않는다.
