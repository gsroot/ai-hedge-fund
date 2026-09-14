## Why

현재 분석은 Codex가 `.agents/skills`를 실행하는 구조인데 프로젝트 모델 설정이 없고,
README와 CLAUDE.md에는 제거된 `src/` 실행법과 과거 배분 방식이 남아 있다.
사용자가 요청한 GPT-6 Astra를 프로젝트 기본값으로 지정하고 현재 실행 계약을 정리한다.

## What Changes

- 프로젝트 `.codex/config.toml`에 `gpt-6-astra`와 기존 유효 추론 수준 `xhigh`를 지정한다.
- AGENTS.md와 금융 스킬에 작업 지속, 독립 관점, 데이터와 지시의 구분, 구조화된 출력 원칙을 정리한다.
- README와 CLAUDE.md를 현재 스킬 실행 구조로 맞추고 레거시 웹앱의 상태를 설명한다.
- 마이그레이션 근거, 로컬 검사와 실제 모델 실행의 경계를 기록하고 Agent OS에 연결한다.

## Capabilities

### New Capabilities

- `codex-research-runtime`: Astra 기본값과 스킬 기반 연구 작업의 실행·검증 계약.

### Modified Capabilities

없음. 기존 금융 계산·배분·뉴스 증거 계약은 유지한다.

## Impact

- 기준일: 2026-09-13 Asia/Seoul. Git 기준: `3f080c1`.
- 직접 관찰: `b6d7ac8`에서 레거시 `src/`가 제거되었다. 현재 금융 Python 스크립트에
  OpenAI SDK 호출이 없고 뉴스 분류는 현재 세션 모델을 사용한다.
- 외부 출처: OpenAI 공식 Astra 마이그레이션 지침과 Codex 설정 참조.
- Provider: Codex의 기존 인증·provider를 유지한다. 금융 데이터 provider 설정은 변경하지 않는다.
- 검증: TOML 구문·값·범위, 현재 금융 테스트, 스킬 미러, OpenSpec strict validation,
  `git diff --check`, Agent OS doctor. 모델 품질·계정 접근·새 세션 적용은 별도 실행 근거가 필요하다.
- 실패 상태: 설정 무시(프로젝트 미신뢰 또는 명시적 세션 override), 모델 접근 실패,
  provider 누락·timeout·stale은 실제 분석 성공이나 중립 시장 신호로 바꾸지 않는다.
- 포트폴리오 제약: 사용자 유동성·통화·손실 제약과 주식·섹터·ETF 한도, 합계 100%를 유지한다.

## Non-goals

실제 금융 주문·자금 이동·성과 보장, 유료 provider 활성화, 외부 게시·커밋·푸시,
삭제된 `src/` 또는 레거시 웹앱의 복원, API 어댑터·SDK 신규 도입, 과거 스냅샷 수정,
Claude 모델 핀 변경, 전역 Codex 설정 또는 플러그인 레지스트리 복구는 포함하지 않는다.
