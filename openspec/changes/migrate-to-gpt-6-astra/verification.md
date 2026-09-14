# Verification Report: migrate-to-gpt-6-astra

기준일: 2026-09-13 Asia/Seoul. Git base: `3f080c1`.
범위: 프로젝트 Codex 설정·프롬프트·안내의 로컬 마이그레이션.

## Completeness

제안의 3개 요구사항, 6개 시나리오를 아래와 같이 대조한다. 작업 상태의 기준은 tasks.md다.

| 요구사항 / 시나리오 | 구현·관찰 근거 | 검증 수준 |
|---|---|---|
| 프로젝트 Astra 기본값 / 새 세션 설정 | `.codex/config.toml`: model=gpt-6-astra, model_reasoning_effort=xhigh; 두 키만 존재 | TOML 정적 검증. 새 세션 로드 실험은 미실행 |
| 프로젝트 Astra 기본값 / override 또는 미확인 런타임 | README와 docs/GPT_6_ASTRA_MIGRATION.md에 신뢰·override·실제 선택 확인 명시 | 공식 설정 계약과 문서 대조 |
| 완결성과 독립 분석 / 앙상블 | AGENTS.md, 두 investor-analysis 미러에 관점별 입력 분리·모델 상속 명시 | 프롬프트 대조. Astra 행동 eval은 미실행 |
| 완결성과 독립 분석 / 누락 또는 과거 자료 | 기존 금융 게이트 보존; provider·날짜·가격·사용자 제약 테스트 | 로컬 모의 입력 검증 |
| 현재 경로와 증거 / 뉴스 분류 | 뉴스 스크립트는 현재 스킬 모델용 작업을 준비·집계하고 SDK를 호출하지 않음 | 기존 PointInTimeTests의 뉴스 테스트 및 소스 변경 없음 |
| 현재 경로와 증거 / 검사 완료 보고 | README, 마이그레이션 기록, 이 검증서에 로컬/외부/품질 구분 | 문서 대조 |

## Correctness

### 금융 회귀

실행 명령:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -q
```

결과: **104 tests, OK**, 테스트 본문 2.404초. Python 3.12 기존 가상환경을 사용했다.
pytest가 설치되지 않아 pytest 명령은 실행되지 않았다. 테스트는 기존 unittest 형식이므로
추가 패키지 설치 없이 unittest discovery로 실행했다. 최초 샌드박스 실행은 임시 디렉터리
접근 제한으로 10건 오류가 났고, 승인된 동일 명령의 샌드박스 밖 실행에서 전부 통과했다.

주요 검증 근거:

- `tests/test_financial_skills.py`: 현재 스킬 모델용 뉴스 작업 준비/집계, 외부 LLM 의존성 부재,
  검증되지 않은 뉴스의 순위 영향 차단, 미래 자료 제외와 evidence 직렬화.
- `tests/test_portfolio_decision.py`: 유동성·통화·자산 유형 한도, 모든 가격 실패 시 거절,
  stale/revised 자료, 추천 스냅샷 무결성 및 CLI → 보고서/스냅샷 → 사후 평가.
- `tests/test_provider_readiness.py`: provider 상태·자격 증명 존재 여부·실패 분류.

이번 변경에는 금융 Python 코드·테스트·fixture·lockfile 변경이 없다. 통과 후 테스트를
반복 실행하지 않았고, 문서와 프로젝트 TOML은 별도로 검사한다.

### 설정·문서·OpenSpec

- `tomllib`로 프로젝트 모델/추론 두 키의 값과 다른 override가 없음을 확인했다.
- investor-analysis와 portfolio-report의 Codex/Claude 미러 2쌍이 각각 byte 단위로 동일하다.
- 새 안내의 로컬 Markdown 링크 26개가 존재하며 CLI 파일 경로를 확인했다.
- `analyze_stocks.py`, `data_fetcher.py`, `generate_portfolio_report.py`의 `--help`가 exit 0이다.
- `openspec validate migrate-to-gpt-6-astra --strict`가 통과했다.
- `git diff --check`와 신규 문서/TOML의 별도 whitespace 검사가 통과했다.
- 금융 스크립트·테스트·fixture·의존성·Claude 모델 핀·웹 엔진·과거 포트폴리오는 Git HEAD와 동일하다.
- 완료 전 Agent OS doctor: WARN 1 / FAIL 0. 경고는 시작과 같은 registry drift(missing=55, stale=50)다.

## Coherence

`src/`가 삭제된 스킬 기반 구조를 유지한다. 레거시 웹앱은 복원하지 않았고 그 모델 선택이
Codex를 제어하지 않음을 문서화했다. 전역 설정·인증·보안·Claude 모델 핀과 기존 금융
배분/뉴스 계약을 바꾸지 않았다. 프로젝트 설정은 사용자가 요청한 모델만 지정한다.

## Issues and limits

CRITICAL: 로컬 마이그레이션 요구사항에 알려진 미구현 항목은 없다.

WARNING: 기존 `PLUGIN_CAPABILITY_REGISTRY_DRIFT`가 남아 있다. 시작 시 missing=55,
stale=50이며 모델 설정 변경으로 해결할 문제가 아니다. 전역 레지스트리는 수정하지 않았다.

미검증: 신뢰된 새 Codex 세션에서 기본값이 실제 선택되는지, 계정의 Astra API 접근,
실제 Astra 분석·뉴스 분류 품질, 금융 provider 현재 상태, 비용/지연, OOS 성과.
설정·프롬프트 변경과 기존 모의 금융 테스트는 이 항목들의 통과 증거가 아니다.

기존 best-effort-portfolio-decisions의 새 추천/구성 후 평가 및 point-in-time-evidence-gates의
남은 실증 작업은 유지한다. 커밋·푸시·배포·보고서 신규 생성·아카이브는 수행하지 않았다.

## Commit preparation: 2026-09-14

사용자가 이번 마이그레이션의 커밋·푸시를 요청했다. 앞선 미게시 기록은 2026-09-13 당시
상태다. 게시 범위는 이번 설정·지침·문서와 OpenSpec/Agent OS 기록으로 한정한다.
금융 코드·테스트·기존 포트폴리오는 변경하지 않는다.

직접 관찰: 시작 시 `git fetch origin` 후 main과 origin/main의 차이는 0/0이었다.
Agent OS doctor는 PASS 1 / WARN 0 / FAIL 0으로 이전 registry drift 경고를 보고하지 않았다.
현재 매니페스트에서는 그 경고만 제거하고 당시 관측 기록과 금융·실제 모델 검증 게이트를
보존했다. 전역 레지스트리의 복구 원인이나 복구 주체는 이번 작업에서 확인하지 않았다.
