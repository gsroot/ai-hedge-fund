## Purpose

추천 당시의 자료와 판단을 보존하고 이후 실제로 관측할 수 있는 수익·위험·가설 변화와 연결한다. 성공과 실패를 모두 평가해 다음 의사결정을 개선하며, 사후에 알게 된 정보를 과거 추천에 섞거나 관측 성과를 미래 보장으로 표현하지 않는다.

## ADDED Requirements

### Requirement: Decisions are frozen before evaluation

시스템은 추천 식별자, 생성 시각, 자료 기준일, 입력 참조와 무결성 정보, 방식 버전, 가정·비중·비교 기준·평가 규칙·재검토 조건을 고정된 스냅샷으로 저장해야 한다(SHALL). 변경된 추천은 이전 결정을 참조하는 새 기록으로 저장해야 하며(SHALL), 기존 결정을 소급 수정해서는 안 된다(MUST NOT).

#### Scenario: Recommendation changes after earnings
- **WHEN** 실적 발표 후 가격 가정이나 비중을 바꾸는 경우
- **THEN** 시스템은 이전 추천을 보존하고 새 추천의 시각과 변경 이유를 기록한다
- **THEN** 이전 추천의 사후 평가는 당시 고정한 입력과 비중을 사용한다

### Requirement: Evaluation uses investable and comparable periods

시스템은 추천 생성·자료 확정 이후 실제 거래 가능한 시점부터 평가하고 체결 기준, 배당, 비용, 현금 수익, 기준 통화와 환율 가정을 명시해야 한다(SHALL). 포트폴리오와 비교 지표는 같은 기간·통화·총수익 기준을 사용해야 한다(SHALL). 구성 전 기간의 결과를 이 추천의 실적으로 제시해서는 안 된다(MUST NOT).

#### Scenario: Decision formed after market close
- **WHEN** 종가 이후 생성한 추천을 평가하는 경우
- **THEN** 시스템은 추천 생성과 자료 기준 시각 이후의 다음 거래 가능 시점부터 정해진 체결 규칙을 적용한다
- **THEN** 추천 전에 발생한 당일 수익은 제외하고 비교 지표에도 동일한 시작·종료 규칙을 적용한다

### Requirement: Evaluation failures remain visible

시스템은 예정 평가일 이전에는 미도래 상태를 반환하고, 누락·인증 실패·timeout·거래 정지·상장폐지·수정 데이터는 원인과 적용 범위를 표시해야 한다(SHALL). 누락 수익을 0이나 자동 중립으로 대체하거나 평가 가능한 승자만으로 전체 성과를 계산해서는 안 된다(MUST NOT). 부분 결과는 미완료로 구분하고 데이터 수정 재계산은 기존 결과를 보존한 새 버전으로 저장해야 한다(SHALL).

#### Scenario: One holding lacks a terminal price
- **WHEN** 평가일에 한 편입 자산의 가격을 확인할 수 없는 경우
- **THEN** 시스템은 그 자산을 제외한 평균을 전체 포트폴리오 수익으로 표시하지 않고 평가 불완전 상태와 영향을 표시한다

#### Scenario: Provider revises a historical observation
- **WHEN** 이미 평가한 가격 또는 배당 자료가 수정된 경우
- **THEN** 시스템은 수정 출처와 이유를 가진 새 평가 버전을 만들고 이전 추천과 평가를 보존한다

### Requirement: Outcome and decision quality are evaluated separately

시스템은 실현 총수익·비교 지표와의 차이·위험·현금 및 자산별 기여를 가격 가정·사업 가설·반증 조건의 변화와 구분해 보고해야 한다(SHALL). 좋은 결과와 나쁜 결과를 동일한 규칙으로 포함하고 표본 기간·방법 변경·미평가 결정을 공개해야 한다(SHALL). 단일 평가 구간을 장기 실력의 입증으로 취급하거나 단기 하락만으로 투자 가설을 자동 폐기해서는 안 된다(MUST NOT).

#### Scenario: Negative relative return with an intact business thesis
- **WHEN** 포트폴리오가 비교 지표에 뒤처졌지만 주요 사업 가설의 반증 여부는 확인되지 않은 경우
- **THEN** 시스템은 상대 손실과 원인을 기록하면서 가설 검토 상태를 별도로 표시한다
- **THEN** 손실 구간을 삭제하거나 자동으로 전략 성공·실패를 확정하지 않는다
