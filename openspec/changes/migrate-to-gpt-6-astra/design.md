## Context

동기는 proposal.md를 따른다. 현재 `.agents/skills/investor-analysis/SKILL.md`는 뉴스 분류에
외부 LLM 호출을 금지하고 세션 모델을 사용한다. `tests/test_financial_skills.py`도 이를 검사한다.
`b6d7ac8`은 레거시 `src/`를 삭제했다. `app/backend/routes/language_models.py`는 여전히
없는 `src.llm.models`를 import한다. 그 기본값만 치환하면 실행 가능한 마이그레이션이 되지 않는다.

현재 사용자 설정에서 확인한 유효 모델/추론 기본값은 `gpt-6-astra`/`xhigh`다.
전역 파일은 변경하지 않고 프로젝트 선택만 재현 가능하게 만든다.

## Goals / Non-Goals

**Goals:** 현재 Codex 스킬 실행을 Astra에 맞게 설정하고 모델이 읽는 상충된 안내를 정리한다.

**Non-Goals:** 기존 수치 계산, JSON 스키마, 과거 추천·벤치마크, Claude의 `sonnet` 핀,
레거시 SDK 의존성을 변경하지 않는다. API 인증을 새로 구성하거나 기존 웹앱을 복원하지 않는다.

## Decisions

1. `.codex/config.toml`에는 모델과 추론 수준만 넣는다. 전역 설정 변경은 다른 프로젝트에
   영향을 주고, Markdown의 모델 지정만으로는 런타임이 바뀌지 않으므로 사용하지 않는다.
2. AGENTS.md에는 Astra 작업 지속·입력 신뢰 경계·출력 원칙을 간결하게 기록한다.
   investor-analysis와 portfolio-report에는 관점 분리 및 가정 처리에 필요한 지침만 추가한다.
   공통 금융 지침은 `.claude/skills`에도 대응 반영하되 Claude 전용 모델 라우팅을 유지한다.
3. README를 현재 `.agents/skills` 중심으로 갱신하고 CLAUDE.md는 공통 계약을 참조하게 한다.
   app/README.md에는 레거시 상태를 명시한다. API endpoint를 새로 만드는 대안은 기존
   no-external-LLM 계약을 바꾸므로 채택하지 않는다.
4. 기존 unittest로 금융 계산·실패 처리·JSON 직렬화·뉴스 API 독립성을 검증한다.
   설정과 문서 변경을 그대로 따라 쓰는 신규 테스트는 만들지 않고 TOML·링크·미러를 직접 검사한다.
5. 매니페스트를 이번 change/Git 기준에 연결하고 이전 portfolio change와 남은 외부 게이트를
   보존한다. 완료 상태는 로컬 마이그레이션 범위만 뜻한다.

공식 근거(2026-09-13 확인):
- [Astra 마이그레이션](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra.md#migration-quickstart)
- [Astra 프롬프트 지침](https://developers.openai.com/api/docs/guides/latest-model#prompting-best-practices)
- [Codex 설정 참조](https://learn.chatgpt.com/docs/config-file/config-reference#configtoml)

## Risks / Trade-offs

- 프로젝트 미신뢰 또는 세션 override → 새 작업의 모델·추론 UI에서 확인해야 함을 안내한다.
- Astra의 질문·과도한 설명 → 필요한 질문으로 한정하고 JSON 계약·간결한 근거를 우선한다.
- 긴 컨텍스트의 결론 오염 → 독립 관점에는 다른 의견이나 최종 비중을 전달하지 않는다.
- 금융 정보에 포함된 지시 → 분석 자료로 취급하며 실행 권한을 부여하지 않는다.
- API를 사용하는 레거시 경로의 미지원 → 복원 시 필요한 Responses/파라미터 게이트만 기록한다.
- 기존 Agent OS registry drift → 경고를 유지하며 이번 설정 검증과 분리한다.

## Migration Plan

제안·spec·tasks 작성 후 사용자가 요청한 로컬 마이그레이션을 적용하고 verify한다.
되돌릴 때는 이번 `.codex/config.toml`의 프로젝트 override와 문서 변경만 되돌린다.
기존 전역 설정, 데이터, 금융 스크립트와 스냅샷은 보존된다. 커밋·푸시·아카이브는 수행하지 않는다.
