# AI Hedge Fund repository instructions

## 제품·안전 경계

- 이 저장소는 교육·연구용 proof of concept다. 실제 거래, 자금 이동, 투자 자문, 수익 보장으로 취급하지 않는다.
- 가격·재무·뉴스·구성 종목은 시점에 따라 변한다. 분석 전에 기준 시각과 provider를 확인하고, 현재성이 필요한 사실은 공식 또는 1차 출처로 다시 검증한다.
- 누락·timeout·자격 증명 실패를 실제 0, 중립 신호, 부정 신호로 바꾸지 않는다. 증거가 부족하면 `prior_only`, `unvalidated` 또는 중단 상태를 명시한다.
- 미래정보 누수, survivorship bias, 수정 후 데이터, 시점이 다른 팩터·뉴스를 섞지 않는다. 포트폴리오 품질 주장은 point-in-time과 OOS 증거가 있을 때만 허용한다.

## 필수 분석 흐름

- 포트폴리오 요청은 `predict -> 독립 investor-analysis -> risk snapshot -> portfolio-report` 순서를 유지한다.
- 투자자 관점은 서로 독립적으로 산출한 뒤 결합한다. 한 에이전트의 결론을 다른 에이전트의 입력 결론으로 사용하지 않는다.
- 뉴스는 `.agents/skills/predict/references/news_validation_contract.md`, 팩터는 `.agents/skills/backtesting/references/factor_evidence_contract.md`의 게이트를 따른다.
- 순위, 추천, 예상 수익에는 데이터 기준일, provider, 실패·대체 경로, 불확실성, 제약 조건을 함께 표시한다.

## Agent OS 제어면

- 중요한 분석·파이프라인 변경은 먼저 `.agent-os/manifest.json`을 읽는다. 현재 목표·생명주기·다음 게이트의 기준 문서는 이 매니페스트다.
- 변경 의도·수용 기준·여러 세션의 실행 순서는 OpenSpec change의 산출물과 `tasks`를 기준으로 관리한다. OpenSpec change를 아카이브하기 전 `verify`를 수행하고 동일한 실행 상태를 다른 체크리스트에 중복 기록하지 않는다.
- 장기 작업은 매니페스트의 `work_id`, `active_change`, `next_gate`와 OpenSpec tasks, Git 근거로 복구한다. 별도 작업 그래프는 독립된 근거와 명시적 승인 없이 도입하지 않는다.
- 구현, 로컬 재현, 외부 provider 검증, 보고서 생성, 공개 공유를 별도 상태와 증거로 보고한다.
- 현재 장기 결과의 식별자는 `.agent-os/manifest.json`의 `workflow.work_id`다. 승인된 OpenSpec change와 Git 근거를 이 ID에 연결하고, 외부 게이트 때문에 제안 전이면 `active_change`를 비우고 `next_gate`에 진입 조건을 기록한다. 시작·인계·완료 전 `py -3 C:\Users\gsr27\.codex\agent-os\scripts\doctor.py --repo .`의 경고를 확인한다.

## 구현·검증

- 명령과 구조를 추정하지 말고 `pyproject.toml`, 기존 스크립트, 테스트, skill 문서를 먼저 확인한다.
- 변경 범위에 맞는 테스트와 정적 검사를 실행하고 `git diff --check`를 확인한다.
- 생성 보고서만 보고 파이프라인이 맞다고 판단하지 않는다. 입력 스냅샷, 중간 증거, 제약 검사, 직렬화 결과를 함께 검증한다.
- `.env`, API 키, 유료 provider 응답 원문, 개인 데이터는 커밋하지 않는다.

## Git

- 이 저장소는 unrelated dirty change가 많을 수 있다. 사용자 변경을 보존하고 요청한 경로만 명시적으로 스테이징한다.
- 커밋 전 `git diff --cached --stat`과 cached diff를 확인한다. 사용자가 요청하지 않으면 push, PR, 실제 외부 게시를 하지 않는다.
