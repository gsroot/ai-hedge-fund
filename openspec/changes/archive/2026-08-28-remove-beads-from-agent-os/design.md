## Context

현재 `.agent-os/manifest.json`은 `point-in-time-evidence-gates`와 같은 이름의 활성 OpenSpec 변경을 가리키며, `.beads`는 provider 준비, point-in-time·OOS 검증 뒤 fail-closed 산출물 적용 순서를 기록한다. 원격에는 `refs/dolt/data`(`a3ed0765f428246bbcfdbebf5cbce675cf94e3d7`)와 `refs/heads/__dolt_remote_info__`(`ca1728061586a10c30e9c1d82ed355ba3b8c3e4f`)가 있다.

## Goals / Non-Goals

**Goals:**
- 증거 게이트의 작업 순서와 실패 경계를 보존한다.
- Beads 없이 매니페스트와 활성 OpenSpec에서 상태를 복구한다.
- 연구·포트폴리오 이력과 원격 일반 ref를 보존한다.

**Non-Goals:**
- provider, as-of 시각, 팩터·뉴스, 산출물 또는 포트폴리오 제약을 변경하지 않는다.
- live trading, 자금 이동 또는 성과 보장 기능을 추가하지 않는다.

## Decisions

1. 매니페스트는 현재 목표·증거 게이트, 활성 OpenSpec은 구현·검증 체크리스트를 소유한다.
2. Beads의 `provider 준비 및 계약 -> point-in-time·OOS 검증 -> fail-closed 산출물 적용` 순서를 활성 변경과 대조하고 누락 시 그 산출물에 먼저 보완한다.
3. 전역 Agent OS 변경 뒤 프로젝트 `task_system`·`beads_root`, `AGENTS.md`, `.beads`를 제거한다.
4. 원격 ref 이름과 SHA는 적용 직전 재검증하며 불일치 시 외부 삭제를 중단한다.

## Risks / Trade-offs

- [증거 게이트 순서 손실] → 활성 OpenSpec과 Beads issue를 적용 전에 교차 대조한다.
- [연구 코드나 산출물의 우발적 포함] → 명시된 운영 경로만 stage하고 diff를 검사한다.
- [원격 ref 오삭제] → 예상 이름·SHA가 모두 일치할 때만 삭제한다.
- [별도 그래프 표현력 감소] → 복잡도가 실제로 재발할 때 승인된 대안을 평가한다.

## Migration Plan

1. 전역 Agent OS와 사용자 전역 규칙에서 Beads 필수 의존성을 제거한다.
2. 활성 `point-in-time-evidence-gates`가 세 단계의 의존 순서를 보존하는지 확인한다.
3. 매니페스트와 프로젝트 `AGENTS.md`를 갱신하고 `.beads`를 삭제한다.
4. OpenSpec 검증, Doctor, `git diff --check`와 관련 연구 계약 검사를 실행한다.
5. 예상 SHA를 재확인하고 Beads 전용 원격 ref만 삭제한다.
6. 원격 ref 삭제 후 문제가 생기면 기록된 SHA로 전용 ref만 복구한다.
