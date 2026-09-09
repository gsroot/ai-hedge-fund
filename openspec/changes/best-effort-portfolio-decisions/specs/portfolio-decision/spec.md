## Purpose

현재 이용 가능한 자료와 사용자 제약을 종합해 개별 주식·ETF·현금의 구체적인 추천 비중을 결정한다. 장기 복리 성과의 개선을 목표로 판단 근거와 불확실성을 기록하며, 추천을 내리는 행위와 이미 성과가 입증되었다는 주장을 구분한다.

## ADDED Requirements

### Requirement: Current recommendation and performance evidence are separate

시스템은 유효한 현재 입력으로 최선이라고 판단한 포트폴리오를 제시해야 한다(SHALL). 추천 상태와 성과 검증 수준을 별도로 표시해야 하며(SHALL), `prior_only`, OOS 부재 또는 미래 수익을 보장할 수 없다는 이유만으로 추천을 중단하거나 비중을 자동 축소해서는 안 된다(MUST NOT). 실현 우월성·정확도 주장은 해당 방법의 시점 정합성과 독립 평가 근거를 요구해야 한다(SHALL).

#### Scenario: Current evidence without OOS history
- **WHEN** 현재 가격·사용자 맥락·투자 판단 입력이 유효하지만 전략의 OOS 실적이 없는 경우
- **THEN** 시스템은 구체적인 비중과 판단 근거를 담은 추천을 생성하고 성과 검증 수준을 별도로 `prior_only`로 표시한다
- **THEN** 경험적으로 입증된 초과수익 또는 예측 정확도 수치를 생성하지 않는다

### Requirement: User constraints remain distinct from strategy ambition

시스템은 장기 복리 목표, 평가 기간, 자금 사용 시점·필요액·통화, 손실 감내 제약, 기존 보유 정보와 알려지지 않은 항목을 구분해야 한다(SHALL). 새로운 일반적 장기 목표가 기존 유동성 제약을 암묵적으로 삭제해서는 안 된다(MUST NOT). 필요한 금액이 알려지지 않으면 가정을 명시한 조건부 배분을 제시하고 해결해야 할 입력을 표시해야 한다(SHALL).

#### Scenario: Long-term objective with possible spending in one to three years
- **WHEN** 장기 수익 목표와 1~3년 내 자금 사용 가능성이 함께 입력되었지만 필요액은 알려지지 않은 경우
- **THEN** 시스템은 두 정보를 모두 유지하고 유동성 확보 가정에 따른 조건부 배분을 제시한다
- **THEN** 가정한 필요액이나 투자 가능 금액을 사용자가 확인한 사실로 표시하지 않는다

### Requirement: Independent evidence informs explicit investment judgment

시스템은 `predict -> independent investor-analysis -> risk snapshot -> portfolio-report` 흐름과 투자자 관점의 독립성을 유지해야 한다(SHALL). 최종 선택은 가격 대비 가치·사업 전망·반대 근거·대안·위험을 종합한 판단을 포함해야 하며(SHALL), 점수·confidence·다수결만으로 비중을 결정해서는 안 된다(MUST NOT). 일부 관점의 자료 부족은 원래 상태로 기록하고 해당 자산 판단에 미치는 중요성을 평가해야 한다(SHALL).

#### Scenario: One investor perspective has insufficient evidence
- **WHEN** 하나의 독립 관점은 `insufficient`이고 다른 자료에는 투자 판단에 필요한 근거가 있는 경우
- **THEN** 시스템은 자료 부족의 영향을 설명하고 해당 종목을 선택하거나 제외할 수 있다
- **THEN** 누락된 관점을 중립·약세·0점으로 대체하거나 관점 하나의 부족만으로 자동 제외하지 않는다

### Requirement: Stocks and ETFs compete as investment alternatives

시스템은 주식과 ETF를 자산 성격에 맞는 기준으로 비교하고 선택·제외 근거를 남겨야 한다(SHALL). 특정 자산 유형을 항상 우선하거나 일정한 비중을 의무 배정해서는 안 된다(MUST NOT). ETF는 추종 대상·구성 기준일·보수·통화·집중도·레버리지 여부를 검토하고, 회사 전용 재무 지표 부재로 자동 제외해서는 안 된다(MUST NOT).

#### Scenario: Diversified ETF is the preferred available investment
- **WHEN** 비교 판단상 분산 ETF가 선호되고 사용자 제약이 해당 비중을 허용하는 경우
- **THEN** 시스템은 ETF에 개별 회사의 비중 상한을 잘못 적용하지 않고 그에 맞는 비중을 추천한다

#### Scenario: Individual stocks have stronger investment cases
- **WHEN** 개별 종목의 가격·사업 근거와 위험 대비 매력이 비교 ETF보다 낫다고 판단한 경우
- **THEN** 시스템은 그 판단과 반증 조건을 기록하고 제약 안에서 개별 종목에 비중을 배정한다
- **THEN** 지수 ETF보다 낫다는 실현 성과가 없다는 이유만으로 이 판단을 기각하지 않는다

### Requirement: Thesis and sizing are reviewable

각 추천 자산은 기준 가격·통화·시각, 출처가 있는 사실, 가정, 선택 이유, 비교 대안, 하방 위험, 반증·재검토 조건, 비중 근거를 포함해야 한다(SHALL). 가격 시나리오를 제시할 때는 기간·계산 방식·가정과 총수익 구성요소를 명시해야 한다(SHALL). 점수나 confidence를 수익률·성공 확률로 바꾸어서는 안 된다(MUST NOT). 보유 정보가 없으면 목표 비중을 제시하되 실제 매매 수량을 생성해서는 안 된다(MUST NOT).

#### Scenario: Attractive score without a defensible price model
- **WHEN** 높은 순위의 종목에 대해 정밀한 가격 모델을 만들 근거가 충분하지 않은 경우
- **THEN** 시스템은 근거의 한계를 명시하고 정성적 판단 또는 가정 범위로 추천 여부와 비중을 결정한다
- **THEN** 해당 점수를 예상 수익률이나 보정된 확률로 표현하지 않는다

### Requirement: Cash reflects an explicit decision

시스템은 지출 준비금·투자 기회·위험·현금 수익과 기회비용을 검토한 현금 비중을 명시해야 한다(SHALL). 시장 국면의 현금 규칙은 판단 자료로 제공하고 조정 이유를 기록해야 한다(SHALL). 배분 계산의 잔액을 의도한 현금 전략으로 자동 확정해서는 안 된다(MUST NOT).

#### Scenario: Stock caps leave a large unallocated balance
- **WHEN** 종목 상한 또는 후보 부족으로 초기 배분에 잔액이 발생하는 경우
- **THEN** 시스템은 이용 가능한 ETF·다른 후보·현금 유지의 대안을 비교한 뒤 최종 비중을 결정한다
- **THEN** 최종 현금 비중과 선택 이유를 기록하고 계산 잔액을 선택 이유로 위장하지 않는다

### Requirement: Final allocation satisfies typed constraints

완성된 추천은 자산과 현금의 합계 100%, 비음수·유한 비중, 사용자 유동성 조건, 자산 유형별 한도와 적용 범위가 명시된 집중도 조건을 만족해야 한다(SHALL). 직접 주식의 섹터 한도와 ETF 구성 종목을 합산한 노출은 구분해야 한다(SHALL). 확인되지 않은 ETF 구성은 0 노출이나 분산 검증 통과로 처리해서는 안 된다(MUST NOT). 충족 불가능한 제약은 실패 원인으로 표시해야 한다(SHALL).

#### Scenario: ETF overlaps with direct stock holdings
- **WHEN** ETF와 직접 보유 종목 사이에 중복 노출이 있는 경우
- **THEN** 시스템은 구성 기준일과 계산 가능한 중복 노출을 보고하고 해당 범위의 설정된 한도를 검사한다
- **THEN** 구성 자료가 없어서 필수 한도를 검증할 수 없으면 완료 상태로 표시하지 않는다

### Requirement: Source failure is not an investment signal

시스템은 provider·조회 시각·자료 기준일·공시 가능 시각·대체 경로와 `timeout`, 인증 누락, quota, stale, revision, schema 오류를 기록해야 한다(SHALL). 필수 가격·식별자·판단의 유효성을 검증하고, 실패한 입력은 제외하거나 해당 결정의 완료를 보류해야 한다(SHALL). 유효한 다른 대안의 판단은 계속할 수 있어야 한다(SHALL). 수정된 최신 자료를 과거에 알려진 자료처럼 사용하거나 검증되지 않은 뉴스 감성을 정량 점수에 반영해서는 안 된다(MUST NOT).

#### Scenario: Provider failure affects one candidate
- **WHEN** 한 후보의 가격 조회가 timeout이고 다른 후보들의 가격과 근거는 유효한 경우
- **THEN** 시스템은 실패 후보를 가격 0이나 약세 신호로 변환하지 않고 이용 가능한 후보의 판단을 계속한다

#### Scenario: No actionable current inputs
- **WHEN** 모든 후보의 필수 가격이 누락되거나 허용된 현재성 기준을 벗어난 경우
- **THEN** 시스템은 입력 문제로 추천을 완성할 수 없음을 표시한다
- **THEN** 이 상태를 투자 판단을 마친 현금 100% 추천으로 출력하지 않는다

### Requirement: Reports preserve decisions and legacy reproducibility

새 추천은 판단 방식·상태·근거·가정·제약 검사와 비중을 저장하고 JSON·엑셀·텍스트에서 같은 값을 제공해야 한다(SHALL). 기존 배분 입력의 명시적인 legacy 실행 경로와 기존 보고서 소비자가 사용하는 비중·현금·분석일 필드는 유지해야 한다(SHALL). legacy 재현 결과를 새 판단 방식의 추천으로 표시해서는 안 된다(MUST NOT).

#### Scenario: Round trip and legacy replay
- **WHEN** 새 판단을 저장 후 다시 읽거나 기존 점수 배분 입력을 재실행하는 경우
- **THEN** 새 판단은 근거와 비중이 손실 없이 왕복하고 모든 보고서 형식에서 일치한다
- **THEN** 기존 경로는 기존 배분 결과를 재현하면서 legacy 방식임을 표시한다
