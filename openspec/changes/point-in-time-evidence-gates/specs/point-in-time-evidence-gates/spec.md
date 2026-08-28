## Purpose

투자 연구 파이프라인이 시점 일치 데이터와 독립 검증을 통과한 증거만 순위에 사용하고, 결측·실패·미검증을 중립 신호와 구분해 재현 가능한 연구 산출물을 만들도록 정의한다.

## ADDED Requirements

### Requirement: Provider readiness before ranking
시스템은 순위 생성 전에 필요한 provider의 자격 증명, 표본 호출, 응답 스키마, 데이터 시점과 stale/revised 상태를 확인해야(SHALL) 한다.

#### Scenario: 자격 증명 또는 표본 호출 실패
- **WHEN** 필수 provider 자격 증명이 없거나 표본 호출이 인증, timeout, quota, 스키마 오류로 실패한다
- **THEN** 시스템은 해당 증거를 실제 0으로 대체하지 않고 provider 미준비 상태와 영향 범위를 기록한다

#### Scenario: 유효한 표본 응답
- **WHEN** provider 표본 응답이 성공한다
- **THEN** 시스템은 as-of 시각, 원천, 관측 가능 시점, revision/staleness와 필요한 필드를 기록한 후에만 후속 검증으로 진행한다

### Requirement: Point-in-time and OOS factor evidence
`predict_factor_v1`의 7개 팩터는 신호일 당시 관측 가능한 값, 다음 실제 거래일 체결, 비용, 독립 홀드아웃을 사용해 동일한 계약으로 검증되어야(SHALL) 한다.

#### Scenario: 미래정보 또는 현재 구성종목 소급
- **WHEN** panel에 신호일 이후 정보, 정정 후 값의 빈티지 혼합 또는 현재 구성종목의 과거 소급이 포함된다
- **THEN** 시스템은 해당 panel을 point-in-time 근거로 거부하고 순위 품질 주장을 중단한다

#### Scenario: 근거 등급 적용
- **WHEN** 팩터 evidence JSON이 시장·유니버스·spec ID·validation 종료일 계약과 원시 지표 검증을 통과한다
- **THEN** 시스템은 claimed label을 그대로 신뢰하지 않고 원시 지표에서 등급과 prior multiplier를 재계산한다

### Requirement: Missing evidence is not neutral evidence
시스템은 근거 부재, 모순, provider 실패를 실제 시장 신호 0과 구분해야(SHALL) 하고 `prior_only`, `unvalidated`, `risk_and_explanation_only` 같은 명시적 상태를 사용해야(SHALL) 한다.

#### Scenario: factor evidence가 없음
- **WHEN** 적용 가능한 factor evidence가 없다
- **THEN** 시스템은 prior 상대 비중을 유지하고 `prior_only`와 `unvalidated`를 기록하며 검증된 순위라고 주장하지 않는다

#### Scenario: 모든 팩터가 contradicted
- **WHEN** 검증된 7개 팩터가 모두 contradicted 조건을 충족한다
- **THEN** 시스템은 사전 상대 비중 fallback을 명시하고 `fallback_reason`과 불확실성을 최종 산출물에 남긴다

### Requirement: News requires independent three-part validation
뉴스 점수는 `news_event_v2` semantic, predictive, portfolio 게이트와 sentiment factor evidence가 모두 통과한 경우에만 순위에 영향을 주어야(SHALL) 한다.

#### Scenario: 일부 뉴스 게이트만 통과
- **WHEN** 의미 정확도, 미래 홀드아웃 방향성, 비용 차감 포트폴리오 비교 또는 sentiment factor evidence 중 하나라도 미통과다
- **THEN** 시스템은 뉴스를 `risk_and_explanation_only`로 제한하고 순위 점수를 바꾸지 않는다

#### Scenario: 독립 검증 완료
- **WHEN** 동결된 임계값과 독립 라벨·홀드아웃으로 모든 뉴스 게이트를 통과한다
- **THEN** 시스템은 validation policy ID, 기간, 표본, 지표, 비용과 한계를 기록한 범위에서만 뉴스 순위 영향을 허용한다

### Requirement: Reproducible staged analysis and reporting
시스템은 `predict -> independent investor-analysis -> risk snapshot -> portfolio-report` 순서를 보존해야(SHALL) 하며, 최종 산출물은 데이터 as-of, evidence mode, 제약, provider 실패와 미검증 한계를 포함해야(SHALL) 한다.

#### Scenario: 독립 투자자 분석
- **WHEN** 여러 투자자 관점이 생성된다
- **THEN** 각 분석은 집계 전에 다른 분석의 결론을 보지 않고 사용한 입력 시점과 불확실성을 기록한다

#### Scenario: 최종 보고서 생성
- **WHEN** 포트폴리오 보고서를 생성한다
- **THEN** 시스템은 제약 위반 여부, 데이터 시점, evidence/fallback 상태, 위험과 범위 밖의 실제 주문·성과 보장을 명확히 직렬화한다
