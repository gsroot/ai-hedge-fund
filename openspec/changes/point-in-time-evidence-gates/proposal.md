## Why

현재 포트폴리오 산출물과 팩터/뉴스 계약은 존재하지만, provider 실패·미래정보 누수·OOS 미검증이 중립 신호로 오인되면 정교한 보고서가 잘못된 확신을 강화할 수 있다. 데이터 시점과 독립 검증을 통과한 경우에만 순위 영향을 허용하고, 부족한 증거는 명시적 상태로 중단하도록 변경 계약을 만든다.

## What Changes

- provider 자격 증명, 표본 호출, 스키마, as-of 시점, stale/revised 상태를 순위 생성 전 게이트로 둔다.
- `predict_factor_v1` 7개 팩터를 동일한 point-in-time/OOS 계약으로 평가하고 근거 등급에 따라 prior를 수축한다.
- 근거 부재를 실제 0 또는 중립 신호와 구분해 `prior_only` 또는 `unvalidated`로 기록한다.
- 뉴스는 `news_event_v2` semantic, predictive, portfolio 게이트와 sentiment factor evidence를 모두 통과한 경우에만 순위에 반영한다.
- `predict -> independent investor-analysis -> risk snapshot -> portfolio-report` 순서를 유지하고 데이터 시점·제약·불확실성을 최종 산출물에 직렬화한다.

### Non-goals

- 실제 매수·매도, 주문, 자금 이동, 중개 계정 연결을 수행하지 않는다.
- 검증되지 않은 수익률, 알파, 성과 보장 또는 실전 적합성을 주장하지 않는다.
- 현재 구성종목을 과거 전 기간에 소급하거나 정정 후 데이터를 과거 시점 값으로 취급하지 않는다.
- 유료 provider를 자동 활성화하거나 API 키를 생성·공유하지 않는다.
- 보고서 생성 자체를 파이프라인 건전성의 증거로 사용하지 않는다.

## Capabilities

### New Capabilities

- `point-in-time-evidence-gates`: provider 준비도, 시점 일치 팩터/OOS, 뉴스 독립 검증, 실패 상태와 최종 산출물 provenance를 다룬다.

### Modified Capabilities

없음.

## Impact

- 입력: KRX/S&P 유니버스, 가격·재무·공시·뉴스 provider와 자격 증명, factor panel과 validation JSON.
- 분석: `predict_factor_v1`, `factor_evidence.py`, `news_event_v2`, 독립 투자자 분석과 risk snapshot.
- 출력: `portfolios/krx_20260827`, `portfolios/sp500_20260827` 및 후속 재생성 산출물의 as-of, evidence mode, 제약, 한계 표시.
- 운영: provider readiness나 OOS/news gate 미통과 시 순위 영향 또는 품질 주장을 중단한다.
