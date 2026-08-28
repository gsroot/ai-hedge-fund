## Why

Beads가 사전 비도입 결정과 달리 Agent OS의 필수 실행 상태 계층으로 들어가면서 OpenSpec·매니페스트와 상태가 겹치고 Dolt 전용 원격 ref까지 생성했다. 시점 일치 증거 게이트는 보존하면서 작업 상태 기준을 OpenSpec과 `.agent-os/manifest.json`으로 단순화해야 한다.

## What Changes

- **BREAKING**: Beads를 AI Hedge Fund Agent OS의 필수 작업 시스템과 복구 경로에서 제거한다.
- `point-in-time-evidence-gates`의 provider, point-in-time/OOS, fail-closed 산출물 적용 순서를 활성 OpenSpec 변경과 매니페스트에 보존한다.
- 프로젝트 `AGENTS.md`에서 `bd` 명령과 Beads 루트 연결 의무를 제거한다.
- 저장소의 `.beads` 메타데이터와 Beads가 만든 Dolt 전용 원격 ref를 검증 후 제거한다.
- 전역 Agent OS Doctor가 Beads 부재를 오류로 판단하지 않는 상태에서 프로젝트 검증을 수행한다.
- 비목표: 데이터 provider, 기준 시각, 팩터·뉴스 로직, 포트폴리오 제약, 산출물, 실제 거래 및 수익 주장 정책은 변경하지 않는다.

## Capabilities

### New Capabilities

- `agent-os-control-plane`: Beads 없이 매니페스트와 OpenSpec을 단일 작업·생명주기 제어면으로 사용하는 계약

### Modified Capabilities


## Impact

- 영향 범위: `.agent-os/manifest.json`, `AGENTS.md`, `.beads`, OpenSpec 운영 문서, GitHub의 Beads/Dolt 전용 ref, 전역 Agent OS Doctor 연동
- 비영향 범위: `predict -> independent investor-analysis -> risk snapshot -> portfolio-report`, provider 데이터, 포트폴리오 출력과 검증 결과
- live trading, 자금 이동, 주문 실행과 성과 보장은 계속 명시적으로 제외한다.
