## Purpose

Agent OS가 Beads나 Dolt 저장소에 의존하지 않고도 AI Hedge Fund의 현재 목표, 변경 의도, 실행 순서와 검증 근거를 일관되게 복구하도록 한다.

## ADDED Requirements

### Requirement: Beads 없는 제어면
프로젝트의 Agent OS는 Beads 실행 파일, `.beads` 데이터베이스, Beads 원격 또는 Beads issue ID를 필수 구성으로 요구해서는 안 되며(SHALL NOT), 매니페스트와 OpenSpec만으로 현재 상태를 복구할 수 있어야 한다(SHALL).

#### Scenario: Beads가 설치되지 않은 환경
- **WHEN** 저장소에 `.beads`가 없고 `bd` 실행 파일을 사용할 수 없다
- **THEN** Agent OS Doctor는 그 부재만으로 오류나 미해결 게이트를 만들지 않고 매니페스트와 OpenSpec을 검증한다

### Requirement: 상태와 의존 순서 보존
제거 과정은 현재 `work_id`, 생명주기 상태, 활성 OpenSpec 변경, 다음 게이트와 아직 유효한 선후 관계를 매니페스트 또는 OpenSpec에 보존해야 한다(MUST).

#### Scenario: 장기 작업 재개
- **WHEN** 새 세션이 `.agent-os/manifest.json`과 활성 OpenSpec 변경을 읽는다
- **THEN** Beads 데이터 없이도 provider 준비, point-in-time·OOS 검증, fail-closed 산출물 적용 순서를 식별할 수 있다

### Requirement: Beads 전용 원격 상태의 제한적 제거
원격 정리는 사전에 확인한 Beads/Dolt 전용 ref만 제거해야 하며(MUST), `main`과 일반 제품 브랜치 및 태그를 변경해서는 안 된다(SHALL NOT).

#### Scenario: 원격 ref 정리
- **WHEN** 제거 작업이 원격 저장소에 적용된다
- **THEN** 확인된 `refs/dolt/data`와 `refs/heads/__dolt_remote_info__`만 사라지고 연구·산출물 Git 이력은 유지된다

### Requirement: 연구 동작 보존
이 제어면 변경은 provider, 기준 시각, 팩터·뉴스, 포트폴리오 제약, 직렬화, 검증 결과 및 보고 워크플로를 변경해서는 안 된다(SHALL NOT).

#### Scenario: 구현 diff 검토
- **WHEN** 제거 변경의 Git diff를 검토한다
- **THEN** 변경은 Agent OS·OpenSpec·Beads 운영 경로에 한정되고 연구 코드, 데이터와 산출물은 포함되지 않는다

### Requirement: 재도입의 명시적 승인
Beads 또는 다른 별도 작업 그래프는 향후 독립된 근거와 명시적 승인 없이 자동 초기화되거나 필수 구성으로 승격되어서는 안 된다(SHALL NOT).

#### Scenario: 장기 연구 작업이 시작됨
- **WHEN** 여러 세션에 걸친 작업이 시작된다
- **THEN** 기본적으로 매니페스트와 OpenSpec을 사용하며 별도 작업 시스템은 승인된 변경이 있을 때만 도입한다
