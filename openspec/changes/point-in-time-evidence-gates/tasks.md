## 1. Provider 준비도

- [x] 1.1 KRX와 S&P 파이프라인의 필수 provider, 자격 증명, 필드, as-of, revision, quota를 인벤토리로 만들고 실제 표본 호출 결과로 확인한다
- [x] 1.2 인증·timeout·quota·스키마·stale 실패를 실제 0과 구분하는 구조화 상태를 검증하고 관련 회귀를 보강한다

## 2. Point-in-time 팩터 검증

- [ ] 2.1 시장·유니버스별 historical membership과 빈티지가 있는 월간 panel을 만들고 미래정보·중복 체결일·기간 정렬 검사를 통과시킨다
- [ ] 2.2 7개 `predict_factor_v1` 팩터의 비용 차감 IC, coverage, turnover, ablation, 독립 홀드아웃을 재현하고 원시 지표에서 등급을 재계산한다
- [x] 2.3 evidence 부재·불일치·contradicted에서 `prior_only`, `unvalidated`, `fallback_reason`이 정확히 직렬화되는지 테스트한다

## 3. 뉴스 독립 검증

- [ ] 3.1 결과와 미래 수익률을 보지 않은 독립 gold label로 `news_event_v2` semantic gate를 검증한다
- [ ] 3.2 동결된 미래 홀드아웃과 다음 실제 거래일 체결로 predictive gate를 검증한다
- [ ] 3.3 동일 유니버스·제약·비용의 뉴스 미사용 기준선과 비교해 portfolio gate를 검증하고, 모든 게이트 전에는 `risk_and_explanation_only`임을 확인한다

## 4. 파이프라인 및 산출물

- [x] 4.1 `predict -> independent investor-analysis -> risk snapshot -> portfolio-report` 순서와 분석 독립성을 입력·중간 evidence·출력 assertion으로 검증한다
- [ ] 4.2 포트폴리오 제약, as-of, provider 상태, evidence mode, validation 범위, 미검증 한계가 KRX/S&P 산출물에 정확히 포함되는지 확인한다
- [x] 4.3 결정론적 constraint/test suite와 `git diff --check`를 통과시키고 생성 캐시와 사용자 dirty work를 변경 범위에서 제외한다

## 5. 완료 감사

- [x] 5.1 OpenSpec verify로 spec·구현·provider/OOS/news 증거를 대조하고 미통과 항목을 품질 주장 차단 게이트로 남긴다
- [x] 5.2 검증된 범위만 새 snapshot으로 보고하고 실제 거래·자금 이동·성과 보장·외부 공개를 수행하지 않은 상태를 명시한다
