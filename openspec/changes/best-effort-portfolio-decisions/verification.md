# Verification Report: best-effort-portfolio-decisions

기준일: 2026-09-09. 범위: 로컬 구현과 검증. Git base:
`301dff4141c97678adf311ff569de477b746150e`. 아래는 커밋 전 작업 트리에서 수행한 구현
검증 기록이다. 이후 커밋·푸시 상태는 이 변경의 Git 이력과 원격 브랜치에서 확인한다.

## Summary

| Dimension | Status |
| --- | --- |
| Completeness | 구현 작업 18/18, 요구사항 13/13에 구현·근거 연결 |
| Correctness | 신규 회귀 27개 + 기존 금융 스킬 회귀 68개 통과 |
| Coherence | 명시적 판단·결정론적 검사·legacy 재현·구성 후 평가의 설계와 일치 |

## Evidence

직접 관찰한 검증:

```text
.venv/Scripts/python.exe -m unittest discover -s tests -p test_portfolio_decision.py -q
Ran 27 tests ... OK
.venv/Scripts/python.exe -m unittest discover -s tests -p test_financial_skills.py -q
Ran 68 tests ... OK
```

- skill-creator quick_validate를 Python `-X utf8`로 실행: portfolio-report, predict,
  investor-analysis, backtesting 모두 통과.
- `openspec validate best-effort-portfolio-decisions --strict --no-interactive` 통과.
- `git diff --check` 통과. 스킬 미러 파일은 기존 회귀에 새 파일을 추가해 byte 일치를 확인했다.
- 기존 `portfolios/sp500_20260909`의 predict·독립 분석·risk 입력을 legacy CLI로 임시
  디렉터리에 재실행했다. ADBE .15, INCY .15, NVDA .12, GDDY .079, 현금 .501 및 분석일이
  기존 JSON과 정확히 일치했다. 기존 보고서는 덮어쓰지 않았다.
- skill-creator 지침에 따른 독립 forward test에서 스킬·참조 문서와 가상 원자료만 제공했다.
  구현·테스트 코드는 읽지 않은 에이전트가 첫 실행에 AAA 10%, MARKET 70%, 현금 20%의
  조건부 연구 추천을 만들었다. 예시 배분을 복제하지 않았고 JSON·텍스트·엑셀·스냅샷이
  일치했다. 사용자 준비금 가정과 부족한 독립 관점이 보존됐다.
- forward test에서 지적한 상단 메타데이터 누락, 퍼센트 형식, 부동소수점 표시 문제를
  보완하고 회귀로 확인했다. 워크북 셀·자료 일치를 검증했으며 화면 렌더링 검증은 하지 않았다.

위 fixture와 독립 실행 결과는 계약·실행 가능성 근거다. 실제 투자 성과나 최적성의 증거가 아니다.

## Requirement mapping

아래 파일은 `.agents/skills/portfolio-report/scripts/` 기준이며 같은 `.claude` 미러를 가진다.

| Requirement | 구현 및 시나리오 검증 |
| --- | --- |
| Current recommendation and performance evidence are separate | `portfolio_decision.py:140`의 별도 status/performance_evidence. prior_only 및 불충분 의견에서도 명시적 비중 유지 테스트 |
| User constraints remain distinct from strategy ambition | user_context, 준비금 가정·필요액 환산 검사. 장기 목표·6개월 평가·1~3년 사용 가능성·금액 미상 왕복 및 모순 입력 거절 |
| Independent evidence informs explicit investment judgment | 독립 출처 선언·관점 누락·날짜 검사. insufficient의 자동 제외 제거와 영향 설명 보존. confidence의 비중 환산 없음 |
| Stocks and ETFs compete as investment alternatives | 자산 유형별 제약·ETF 구성/보수/레버리지. ETF 전액·큰 비중 및 주식 혼합 판단 허용. 순위 변경이 판단 비중을 덮어쓰지 않음 |
| Thesis and sizing are reviewable | `_thesis`의 사실 참조·가격 가정·반증·대안·비중 이유. score 기반 시나리오 거절. 보유 미상 target_only, 알려진 보유의 추가/유지/축소/제외 비교 |
| Cash reflects an explicit decision | cash 목적·기회비용·시장 규칙 차이 보존. 참고 10%와 최종 5% 허용. 잔액 합계 오류 및 지출 준비금 위반 거절 |
| Final allocation satisfies typed constraints | 주식·ETF·직접 섹터·전체 issuer/sector 검사. ETF 60% 내부 AAA 10%와 직접 AAA 15%의 합산 21% 검증. 불완전 구성의 필수 한도 통과 금지 |
| Source failure is not an investment signal | `_source_map`, `_refs`, 상태별 입력 처리. timeout/인증/quota/stale/schema, 미래 공시·수정 자료, 실패 후보 제외 후 유효 대안 유지, 전 가격 실패의 현금 100% 위장 금지 |
| Reports preserve decisions and legacy reproducibility | `decision_report.py` 단일 결과→JSON 왕복·엑셀·텍스트. 긴 셀 분할·수식 방지·퍼센트 표시. 실제 이전 JSON 비중 재현 |
| Decisions are frozen before evaluation | `save_snapshot`, `load_snapshot`: ID 배타 저장, SHA-256, 이전 추천 연결, 변조 및 credential 참조 거절 |
| Evaluation uses investable and comparable periods | `evaluate_decision.py:64`: 이후 거래일 시가·최초 비중 매수 후 보유·같은 기간 benchmark. 손계산·매일 리밸런싱과의 차이·배당 중복 방지·현금/비용/환율 기여 합계 검증 |
| Evaluation failures remain visible | 미도래 not_due, 누락·거래 정지·상장폐지·provider 실패 incomplete, 혼합 달력 미지원. 미래/부족한 달력·자료 거절 및 평가 버전 보존 |
| Outcome and decision quality are evaluated separately | 음의 상대 수익 기록과 intact/contradicted/uncertain/not_reviewed 가설 평가 분리. 수정 데이터의 새 hash·버전, 이전 결과 보존 |

## Issues and limitations

구현 범위의 CRITICAL/WARNING 잔여 사항은 없다. 별도 제어면 경고
`PLUGIN_CAPABILITY_REGISTRY_DRIFT` 1건(missing=69, stale=69)은 시작 전부터 존재하며
이번 금융 스킬 변경으로 해결한 것으로 표시하지 않는다.

미검증 또는 별도 범위:

- 새로운 실시간 provider 자료로 만든 실제 투자 추천과 장기 초과성과는 이번에 평가하지 않았다.
- 출처 내용의 진실성, AI 설명의 타당성, 달력 원천의 완전성은 사람이 원자료와 함께 검토해야 한다.
  코드가 유효한 숫자와 구조를 확인했다고 투자 판단이 최적이라고 주장하지 않는다.
- 첫 평가 엔진은 단일 거래소 달력·총수익 조정 OHLC·소수 수량·명시적 비용·세전·최초 비중
  매수 후 보유 범위다. 실제 계좌 체결·세금, 여러 추천을 연결한 리밸런싱 실적과 구분한다.
- 기존 `point-in-time-evidence-gates`의 미완료 실증 자료 작업은 변경 없이 보존했다.
- 구현 검증 단계에서 실제 주문·자금 이동·유료 provider 활성화·외부 게시·스케줄 생성·커밋·push·PR은 수행하지 않았다.

## Assessment

승인된 스킬 개선과 로컬 검증은 완료했다. 현재 추천을 내리는 기본 흐름을 개선했고,
장기 성과는 고정된 추천과 이후 관측으로 평가할 수 있다. 이 기록은 성과 보장이 아니다.
OpenSpec 아카이브는 이번 요청 범위에 포함하지 않았다.
