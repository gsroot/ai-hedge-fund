---
name: portfolio-report
description: |
  현재 자료와 독립 투자 분석으로 개별 주식·ETF·현금의 최선이라고 판단하는 비중을
  추천하고 선택 근거·가격 가정·재검토 조건과 보고서·사후 평가를 남긴다.
  사용 시점: 포트폴리오 구성, 투자 비중 추천, 현금 비중 판단, 엑셀 투자 리포트.
---

# Portfolio Report

사용자의 자금 사용 조건과 위험 감내 범위 안에서 **장기 복리 성과를 최대한 높일
현재의 선택**을 추천한다. 개별 종목·ETF·현금과 목표 비중을 끝까지 판단한다.
어느 자산 유형도 자동 우선하지 않는다. 기존 포트폴리오를 유지하는 결정도 대안이다.

현재 추천과 실증 성과의 입증은 별개다. `prior_only`, OOS 부재, 미래 수익을 보장할
수 없다는 이유만으로 추천을 거절하거나 주식 비중을 자동 줄이지 않는다. 정량 순위·
confidence·설명 길이를 예상 수익이나 최적 비중의 증거로 삼지 않는다.
선택한 안을 그 시점의 가장 추천하는 안으로 제시하고 판단을 바꿀 조건도 설명한다.

## 새 추천 흐름

`predict -> independent investor-analysis -> risk snapshot -> portfolio-report` 순서를 지킨다.
새 추천을 만들 때 [판단 입력 계약](references/decision_contract.md)을 읽는다.

1. 대화에서 알려진 목표·사용 시점·필요액·통화·손실 제약·기존 보유를 정리한다.
   전략의 장기 목표와 평가 기간을 구분하고 알려진 지출 제약을 보존한다.
   미상 값은 가정과 조건부 배분으로 명시하고 중요한 부족 정보만 질문한다.
2. `predict`로 요청 유니버스의 순위를 저장한다. 순위는 조사 우선순위이며 최종 비중이 아니다.
   ETF는 별도 후보로 추가하고 운용사 자료로 구성·보수·통화·집중도·레버리지를 확인한다.
   ETF에 개별 기업용 ROE 등의 지표를 강제로 적용하지 않는다.
3. 선택한 투자자 관점에서 후보를 독립 분석한다. 기본은 `buffett,lynch,fisher`이며 필요한
   관점은 바꿀 수 있다. 다른 관점의 결론이나 최종 비중을 보면서 작성하지 않는다.
   [분석 JSON 형식](references/decision_contract.md#독립-분석)을 따른다.
4. 같은 기준일로 주식·편입/비교 ETF의 위험 스냅샷을 만든다.

```bash
uv run python .agents/skills/portfolio-report/scripts/build_risk_snapshot.py \
  --predict-json results.json --top 30 --extra-tickers SPY,VOO \
  --benchmark SPY --output risk.json
```

5. 현재 스킬을 실행하는 AI가 원자료·독립 의견·위험을 종합해 `decision.json`을 작성한다.
   별도 외부 LLM API를 추가로 호출할 필요는 없다. 기업 공시/IR·운용사 자료를 우선하고
   자료 기준일·공시일·조회일과 출처를 남긴다. [예시 JSON](references/decision_example.json)은
   가상 테스트 자료다. 실제 종목·가격·목표 비중으로 교체하며 예시 숫자를 추천으로 복제하지 않는다.
6. 검증기와 보고서 생성기를 실행한다. 위반이 있으면 이유를 확인하고 판단안을 수정한다.
   유효한 선택을 코드가 점수 공식으로 덮어쓰거나 잔액을 현금으로 자동 확정하지 않는다.

```bash
uv run python .agents/skills/portfolio-report/scripts/generate_portfolio_report.py \
  --predict-json results.json --investor-json investor_results.json --risk-json risk.json \
  --decision-json decision.json --investors buffett,lynch,fisher \
  --portfolio-json portfolios/current.json --output-dir portfolios \
  --snapshot-dir portfolios/decisions --xlsx yes
```

## 최종 판단에서 할 일

- **선택과 가격:** 지금 가격에서 사업 전망·가치·현금흐름을 평가하고 다른 종목·ETF·현금과
  비교해 선택/제외 이유를 쓴다. 매력적인 회사와 매력적인 매수가를 구분한다.
- **반대 근거:** 중요한 하방 경로와 판단이 틀렸음을 드러낼 사건·가격 조건을 쓴다.
  일부 관점의 `insufficient`는 자료의 한계다. 치명적인 공백인지 설명하고 다른 유효한
  근거가 있으면 선택할 수 있다. 실패한 가격을 0이나 약세 신호로 바꾸지 않는다.
- **비중:** 기대와 하방의 비대칭, 근거의 질, 보유 간 중복, 유동성을 종합한다.
  기본 정책은 개별 주식 15%, 직접 주식 섹터 35%, 분산 비레버리지 ETF 100% 상한이다.
  이 수치가 최적이라고 주장하지 않는다. 사용자 한도를 지키고 기본값 조정은 이유와 함께
  기록한다. 집중/레버리지 ETF는 명시적 개별 한도가 필요하다.
- **현금:** 지출 준비금과 전략적 대기를 구분한다. 이자·기회비용·대안의 매력·시장 위험을
  판단한다. 시장 현금 규칙은 참고값이다. 후보 부족이나 상한으로 생긴 잔액은 대안을
  다시 비교한 뒤 배정한다. 종목·ETF·현금의 최종 합계는 100%다.
- **수치의 의미:** 가격 시나리오는 가정·계산·기간·통화를 명시한다. 정밀 수치가 뒷받침되지
  않으면 범위나 정성 판단으로 선택한다. 점수와 confidence를 수익률·성공 확률로 변환하지 않는다.

최종 답변은 추천 배분과 가장 중요한 이유를 먼저 보여준다. 유지·추가·축소 판단은 알려진
보유와 비교하며 보유가 미상이면 목표 비중만 제시한다. 출처·기준일·가정·반증 조건·근거의
한계를 이어서 설명한다. `conditional`은 가정을 명시한 추천이며 추천 포기가 아니다.

## 기록과 사후 평가

추천 ID별 스냅샷에는 당시 판단·자료 참조·입력 hash가 보존된다. 내용을 바꾸면 새 ID와
`previous_decision_id`를 사용한다. 과거 추천을 소급 수정하거나 손실 사례를 삭제하지 않는다.

구성 이후 평가할 때 [사후 평가 계약](references/evaluation_contract.md)을 읽고 실제 거래일·
총수익 조정 가격·비용·환율을 준비한다. 첫 평가 경로는 최초 비중으로 매수 후 보유이며
여러 추천을 계속 따라 리밸런싱한 실적과 구별한다.

```bash
uv run python .agents/skills/portfolio-report/scripts/evaluate_decision.py \
  --snapshot portfolios/decisions/DECISION_ID --prices-json evaluation_prices.json \
  --as-of 2027-03-10T00:00:00Z --reason "구성 후 첫 평가"
```

실현 수익·시장 대비 차이·현금 기여와 사업 가설의 변화를 따로 평가한다. 단기 하락만으로
가설을 버리지 않고 반증이 확인되면 수정한다. 백테스트는 가정·비용·편향을 점검하는 데 계속
사용한다. 다른 전략의 백테스트를 이 판단 방식의 실적으로 전용하지 않는다.

## 기존 점수 배분 재현

이미 만든 보고서를 재현할 때만 [legacy 배분 계약](references/legacy_allocation.md)을 읽는다.
`--decision-json` 없는 기존 CLI 호출은 과거 점수 배분과 비중을 유지하고 legacy로 표시한다.
새 추천에는 위의 판단 입력 경로를 사용한다.
