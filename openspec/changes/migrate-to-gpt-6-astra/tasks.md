## 1. Runtime

- [x] 1.1 프로젝트 기본 모델을 `gpt-6-astra`, 추론을 `xhigh`로 설정하고 TOML 파싱 및 두 키만 존재하는지 확인한다.
- [x] 1.2 AGENTS.md에 현재 실행 경로·작업 지속·데이터 신뢰·검증 범위를 명시하고 금융 안전 계약 보존을 diff로 확인한다.

## 2. Skills and documentation

- [x] 2.1 investor-analysis와 portfolio-report의 독립 관점·현재 모델 상속·구조화 출력 지침을 보완하고 Codex/Claude 미러의 대응 내용을 확인한다.
- [x] 2.2 README, CLAUDE.md, app/README.md와 마이그레이션 문서를 현재 구조에 맞게 정리하고 모든 새 로컬 참조와 CLI 진입점의 존재를 확인한다.

## 3. Verification and handoff

- [x] 3.1 기존 금융 unittest 전체를 통과시키고 뉴스 외부 LLM 금지·데이터 실패·비중 제약·직렬화 검증 결과와 실행 환경을 기록한다.
- [x] 3.2 OpenSpec verify로 requirement/scenario를 산출물에 대조하고 strict validation 및 diff 검사를 통과시킨다.
- [x] 3.3 Agent OS에 이번 change·Git 근거·이전 연구의 후속 게이트를 연결하고 Doctor의 기존 경고와 미실행 모델/provider 검증을 명시한다.
