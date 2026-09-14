# GPT-6 Astra 마이그레이션

기준일: 2026-09-13 Asia/Seoul. 대상: 현재 Codex 금융 스킬 실행 구조.

## 적용 내용

[프로젝트 설정](../.codex/config.toml)에 `gpt-6-astra`와 `xhigh`를 지정했다.
추론 수준은 당시 사용자 설정을 보존한 값이며 비용·속도 최적화 결과가 아니다.
프로젝트가 신뢰된 경우 설정을 로드하고, 명시적 세션 선택은 기본값보다 우선할 수 있다.
새 Codex 작업의 모델·추론 표시로 실제 선택을 확인한다. 기존 세션이 자동 전환되었다고
간주하지 않는다. 인증·provider·보안·전역 설정은 변경하지 않았다.
[공식 Codex 설정 참조](https://learn.chatgpt.com/docs/config-file/config-reference#configtoml)

[AGENTS.md](../AGENTS.md), investor-analysis와 portfolio-report에는 승인된 작업의 지속,
관점별 입력 분리, 현재 모델 상속, 구조화된 출력과 데이터 신뢰 원칙을 반영했다.
이는 Astra 공식 문서의 작업 지속·지시 준수·문체·검증 지침을 이 연구 흐름에 적용한 설계다.
효과는 실제 분석 사례로 별도 평가해야 한다.
[공식 프롬프트 지침](https://developers.openai.com/api/docs/guides/latest-model#prompting-best-practices)

## 호환성 조사

| 항목 | 직접 관찰 | 판단과 처리 |
|---|---|---|
| LLM 호출 | 금융 스크립트에 OpenAI SDK 호출이 없고 세션 모델이 분석한다 | 별도 API·SDK·키를 도입하지 않는다 |
| 기본 모델 | 프로젝트 설정은 없었고 사용자 설정은 Astra/xhigh였다 | 프로젝트 범위에서 재현 가능한 기본값을 추가한다 |
| 독립 관점 | 현재 스킬에 독립 분석 계약이 있다 | 다른 관점의 결론을 입력에 포함하지 않도록 구체화한다 |
| Claude | 전용 에이전트에 `sonnet` 등의 모델 핀이 있다 | 기존 플랫폼 선택을 보존한다 |
| 웹앱 | `src/`는 `b6d7ac8`에서 삭제되었으나 `app/`는 여전히 import한다 | 레거시로 표시하고 모델 문자열·provider 목록은 치환하지 않는다 |
| 금융 산출물 | 기존 검증기와 스냅샷 계약이 있다 | 점수·비중·JSON 스키마·과거 산출물을 보존한다 |

현재 경로에는 아래 API 파라미터가 없어서 직접 변경할 대상이 없다. 향후 레거시 엔진을
복원해 Astra API를 호출한다면 모델명 치환과 함께 다음 항목을 검증해야 한다.

- 도구 호출은 Responses API를 사용한다. Chat Completions 도구 호출로 유지하지 않는다.
- `none`/`minimal` 추론은 `low`에서 비교하고, 다른 유효 추론 수준은 먼저 보존한다.
- `temperature`, `top_p`, `top_logprobs`를 제거한다. Chat Completions의 `logprobs`와
  Responses `include`의 `message.output_text.logprobs`도 제거한다.
- 기존 `prompt_cache_retention`을 사용했다면 `prompt_cache_options.ttl="30m"` 전환을 검토한다.
- EU data residency의 Astra는 `fast`/`priority` 대신 Standard 처리를 사용한다.

이 내용은 현재 스킬에 API 호출을 새로 추가하라는 지시가 아니다.
[공식 Astra 마이그레이션 지침](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra.md#migration-quickstart)

## 검증 범위

설정 파싱, 기존 금융 unittest, 변경된 지침의 미러·링크, OpenSpec strict validation과
공백 검사를 수행한다. 실제 실행 결과와 requirement/scenario 대조는
[verification.md](../openspec/changes/migrate-to-gpt-6-astra/verification.md)에 기록한다.

실제 Astra 신규 분석·유료 API 호출·provider 재조회·모델 간 품질 비교·투자 성과 평가는
이번 로컬 마이그레이션 검증에 포함하지 않는다. point-in-time/OOS/provider 게이트는 유지한다.
2026-09-13에 관측한 `PLUGIN_CAPABILITY_REGISTRY_DRIFT`는 2026-09-14 커밋 준비 시
Doctor 재확인에서 관측되지 않았다(PASS 1 / WARN 0 / FAIL 0). 이 변경에서 전역 레지스트리를
수정한 것은 아니며, 모델 품질이나 금융 증거 게이트 통과를 뜻하지 않는다.

새 세션에서 모델을 확인한 뒤 실제 분석을 평가할 때는 동일한 입력 기준일·원자료로
뉴스 관련성/abstain 처리, 독립 의견, JSON 파싱과 비중 제약을 확인한다. 모델의 설명이
그럴듯하다는 이유로 뉴스 정확도나 수익 개선을 통과로 기록하지 않는다.

## 되돌리기

이번 프로젝트 모델 override를 제거하면 기존 사용자 설정으로 돌아간다. 이후 다른 설정이
추가되었다면 해당 두 키만 되돌린다. 문서는 이번 변경분만 되돌리고 기존 금융 코드·캐시·
포트폴리오 스냅샷과 Claude 모델 핀은 보존한다.
