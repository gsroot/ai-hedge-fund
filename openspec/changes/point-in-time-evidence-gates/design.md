## Context

동기는 `proposal.md`를 따른다. 현재 행동 기준은 `.agents/skills/backtesting/references/factor_evidence_contract.md`, `.agents/skills/predict/references/news_validation_contract.md`, `.agents/skills/predict/SKILL.md`, `.agents/skills/investor-analysis/SKILL.md`, `.agents/skills/portfolio-report/SKILL.md`다. `portfolios/krx_20260827`과 `portfolios/sp500_20260827` 산출물이 존재하지만, 산출물 존재는 provider readiness나 전체 point-in-time/OOS 품질을 증명하지 않는다.

## Goals / Non-Goals

**Goals:**

- 데이터와 validation evidence를 순위에 적용하기 전에 fail-closed 게이트를 둔다.
- 결측·실패·중립값을 서로 다른 상태로 직렬화한다.
- 입력부터 보고서까지 as-of와 evidence provenance를 재현 가능하게 유지한다.

**Non-Goals:**

- broker 연결, 주문, 자금 이동, 성과 보장, 유료 provider 자동 활성화는 구현하지 않는다.
- 서로 다른 시장·유니버스·팩터 spec의 validation을 전이하지 않는다.

## Decisions

### 1. Provider readiness를 분석의 선행조건으로 둔다

각 필수 원천에 최소 표본 호출과 스키마/as-of 검사를 수행하고 실패를 구조화된 missing evidence로 기록한다. 예외를 0으로 채우는 대안은 정보 부재를 중립 신호로 위장하므로 배제한다.

### 2. Validation label 대신 원시 지표를 재계산한다

`factor_evidence.py`의 point-in-time panel, 비용, IC, coverage, ablation, 독립 홀드아웃 지표에서 등급을 다시 산출한다. JSON의 claimed grade를 신뢰하는 대안은 조작·드리프트에 취약하므로 채택하지 않는다.

### 3. 뉴스는 두 계약의 교집합으로만 순위 반영한다

sentiment factor evidence와 `news_event_v2`의 semantic/predictive/portfolio gate를 모두 요구한다. 기사 수나 모델 confidence만으로 순위 반영하는 대안은 관련성·방향·실제 포트폴리오 기여를 증명하지 못한다.

### 4. 독립 분석 후 명시적으로 집계한다

투자자 관점은 서로의 결론을 보지 않은 채 작성하고 risk snapshot에서 공통·충돌·미확인 근거를 집계한다. 단일 합성 프롬프트는 독립성 측정과 반대 근거 추적을 약화하므로 배제한다.

## Risks / Trade-offs

- [Provider 비용·quota로 검증이 중단됨] → 무료/유료를 자동 전환하지 않고 준비 상태와 최소 표본 결과를 기록한 뒤 사람의 선택을 요청한다.
- [Point-in-time 패널 구축 비용] → 시장·유니버스·기간별로 재현 가능한 원천부터 좁게 구축하고 미검증 범위를 명시한다.
- [엄격한 게이트로 순위 영향이 줄어듦] → `prior_only`나 설명 전용으로 안전하게 축소하며 검증되지 않은 정밀함보다 낮은 확신을 택한다.
- [보고서가 품질 증거로 오인됨] → 최종 산출물에 as-of, evidence mode, validation 범위와 미통과 게이트를 의무화한다.

## Migration Plan

1. KRX와 S&P 파이프라인별 provider·필드·as-of·실패 상태 인벤토리를 만든다.
2. 현재 factor/news validation artifact를 계약과 대조하고 재사용 가능한 범위를 판정한다.
3. point-in-time/OOS 표본과 독립 뉴스 검증을 재현하며 실패 시 명시적 축소 상태를 확인한다.
4. predict, 독립 투자자 분석, risk snapshot, report의 provenance 직렬화를 검증한다.
5. 기존 보고서는 과거 snapshot으로 보존하고 새 evidence contract를 통과한 경우에만 새 버전으로 재생성한다.
6. 회귀 시 순위 영향 기능을 끄고 `prior_only`/`risk_and_explanation_only`로 복귀한다.
