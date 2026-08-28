## 1. 전역 선행조건과 상태 보존

- [ ] 1.1 전역 Agent OS 운영 계약·Doctor·사용자 규칙이 Beads를 필수로 요구하지 않는지 확인하고, `rg` 및 Doctor 회귀 검사에서 Beads 부재가 오류가 아님을 검증한다.
- [ ] 1.2 활성 `point-in-time-evidence-gates` 산출물이 `provider 준비 및 계약 -> point-in-time·OOS 검증 -> fail-closed 산출물 적용` 순서를 보존하는지 대조하고, 누락됐다면 활성 OpenSpec 산출물에 보완한 뒤 상태를 재확인한다.

## 2. 프로젝트 제어면 정리

- [ ] 2.1 `.agent-os/manifest.json`에서 `task_system`과 `beads_root`를 제거하고 기존 `work_id`, 활성 변경, 생명주기와 다음 게이트가 유지되는지 JSON 파싱 및 Doctor로 검증한다.
- [ ] 2.2 `AGENTS.md`에서 Beads·`bd`·issue graph 강제 규칙을 제거하고 매니페스트·OpenSpec·Git 기준의 복구 계약만 남았는지 `rg`로 검증한다.
- [ ] 2.3 추적 중인 `.beads` 경로를 제거하고 `git diff --name-status`가 연구 코드, provider 데이터, 포트폴리오 산출물을 포함하지 않는지 확인한다.

## 3. 검증과 원격 정리

- [ ] 3.1 `openspec validate remove-beads-from-agent-os --strict`, Agent OS Doctor, `git diff --check`를 실행하고 Beads 관련 오류 없이 통과하는지 확인한다.
- [ ] 3.2 원격 ref가 계획 시점의 `refs/dolt/data=a3ed0765f428246bbcfdbebf5cbce675cf94e3d7`, `refs/heads/__dolt_remote_info__=ca1728061586a10c30e9c1d82ed355ba3b8c3e4f`와 일치하는지 확인한 뒤 두 ref만 제거한다.
- [ ] 3.3 `git ls-remote`와 기본 브랜치 SHA 대조로 Beads/Dolt 전용 ref는 사라지고 `main` 및 일반 Git 이력은 유지됐는지 검증한다.
