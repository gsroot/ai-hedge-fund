---
name: portfolio-report
description: |
  현재 자료와 독립 투자 분석으로 개별 주식·ETF·현금의 최선이라고 판단하는 비중을
  추천하고 선택 근거·가격 가정·재검토 조건과 보고서·사후 평가를 남긴다.
  사용 시점: 포트폴리오 구성, 투자 비중 추천, 현금 비중 판단, 엑셀 투자 리포트.
---

# Portfolio Report

사용자가 돈을 쓸 시점과 감당할 수 있는 손실을 먼저 확인한다. 그런 다음 현재 가격에서
장기 복리에 가장 유리하다고 판단하는 **하나의 목표 배분**을 정한다. 비교 범위에는 개별 주식,
분산 ETF, 현금, 기존 보유 유지가 들어간다. 최종 판단은 이 스킬을 실행하는 모델이 내린다.

## 1. 투자 조건과 조사 후보를 정한다

- 알려진 목적, 평가 기간, 지출 시기·금액·통화, 확정 한도, 현재 보유를 [판단 입력 계약](references/decision_contract.md)에 따라 정리한다.
  보유가 일부만 알려졌으면 확인된 비중을 그대로 적는다. 현금이 있다면 현재 보유한 통화도
  확인한다. 미확인 잔액이나 통화를 목표 현금으로 간주하지 않는다.
- `predict -> independent investor-analysis -> risk snapshot -> portfolio-report` 순서를 따른다.
  predict의 전체 순위와 `research_shortlist.candidates`에서 업종·스타일이 다른 후보까지 살펴본다.
  편입 대상 밖의 기존 보유와 실제 편입 가능한 시장 대표 ETF도 조사 목록에 넣는다.
  제약이 중요한 미상 정보만 질문하고 이미 가능한 조사부터 진행한다.
- 독립 투자자 분석에는 공시·공표일과 원자료를 준다. 다른 관점의 결론, 원하는 배분,
  순위 점수에서 환산한 수익률은 주지 않는다. 기본 관점은 `buffett,lynch,fisher`다.
  ETF는 운용사 자료로 추종 대상, 보수, 집중도, 레버리지, 구성 내역을 확인한다.
  편입하려는 주식·ETF에는 요청한 모든 관점의 실제 의견을 확보한다. 자료 부족도 근거와 함께 남긴다.
- 비교에 필요한 상위권 밖 주식, 기존 보유, ETF를 `--extra-tickers`에 포함한다.
  기준 통화가 다르면 필요한 환율 시계열을 `--fx-pair USD/KRW`처럼 지정한다. 자산 가격과 환율을
  같은 평가 기간에 관찰할 수 있는지 확인한다.

```bash
uv run python .agents/skills/portfolio-report/scripts/build_risk_snapshot.py \
  --predict-json results.json --extra-tickers SPY,VOO \
  --benchmark SPY --output risk.json
```

## 2. 같은 조건으로 배분안을 겨룬다

1. 종목마다 지금 가격에 반영된 사업 전망, 현금흐름이나 가치의 변동 범위, 전망을 뒤집을 사실을 기록한다.
   기존 보유라면 보유를 바꿀 근거와 유지할 근거를 모두 검토한다. 같은 발행사·섹터에 직접 보유와
   ETF를 통해 얼마나 노출되는지 확인하고, 예비 투자 비중과 지출 준비금·전략적 현금을 정한다.
2. [v2 입력 예시](references/decision_example.json)의 구조로 `decision.json`을 작성한다.
   비교 시나리오는 동일한 평가 기간과 기준 통화를 쓴다. 기본 가정과 하방 가정 각각에 대해
   현금 이자·분배금·환율을 포함한 자산별 총수익 가정과 근거를 기록한다.
   수치화할 근거가 부족하면 해당 자산을 수익 가정에서 빼고 이유를 설명한다.
3. `--preview`로 예비안을 계산한다. 결과에서 제안 배분과 **시장 ETF+최소 준비금, 전액 현금,
   기존 보유 유지, 적극 보유 비중을 절반으로 낮춘 안**을 비교한다. 보유 유지안은 전체 보유를
   확인한 경우에, 비중 축소안은 비교 ETF 외 자산을 제안한 경우에 계산한다.
   각 대안의 제약 충족 여부, 회전율·전환 비용, 동일한 가정의 손익, 공통 관측 기간의 낙폭을 읽는다.
   ETF와 최소 준비금 조합이 전환 비용이나 하방 손실 한도 때문에 제약을 위반하면,
   제안안과 현금 비중을 맞춘 ETF·현금 조합도 임시 판단안으로 만들어 다시 미리본다.
   필요한 만큼 현금 비중을 높여 같은 제약을 충족하는 조합이 있는지 확인하고, 그 조합과의
   비용·손익 차이 또는 충족할 수 없었던 조건을 최종 ETF 대안 검토 의견에 남긴다.
4. 수수료와 환전 비용을 지불하고도 각 대안보다 제안 배분이 나은 이유를 판단한다. 거래 전환에 비해
   확실한 이점이 적으면 유지안도 선택한다. 선택 근거가 가장 약한 보유는 작은 비중이나 제외를
   검토한다. 필요한 비중을 수정하고 다시 계산한 뒤 각 대안에 대한 상충 관계와 선택이 뒤집힐 조건을
   `comparison.reviews`에 쓴다. 동일한 배분이면 일치하는 이유를 남긴다.

```bash
uv run python .agents/skills/portfolio-report/scripts/generate_portfolio_report.py \
  --predict-json results.json --investor-json investor_results.json --risk-json risk.json \
  --decision-json decision.json --investors buffett,lynch,fisher --preview
```

기본 한도는 직접 주식당 15%, 직접 보유 섹터당 35%, 분산 비레버리지 ETF 100%다.
사용자 한도가 있으면 우선한다. ETF를 통한 전체 발행사·섹터 노출 한도는 별도로 지정한다.
`max_downside_scenario_loss`는 사용자가 명시한 시나리오 손실 기준을 적을 때만 사용한다.
시장 현금 규칙은 참고값이며 현금의 기회비용·이자·유동성과 함께 해석한다.
`prior_only` 또는 일부 미검증 신호가 있어도 유효한 자료와 명시적 가정으로 판단한다.

## 3. 선택과 조건을 기록한다

```bash
uv run python .agents/skills/portfolio-report/scripts/generate_portfolio_report.py \
  --predict-json results.json --investor-json investor_results.json --risk-json risk.json \
  --decision-json decision.json --investors buffett,lynch,fisher \
  --portfolio-json portfolios/current.json --output-dir portfolios \
  --snapshot-dir portfolios/decisions --xlsx yes
```

최종 답변에는 **자산별 비중과 현금 비중, 가장 가까웠던 대안, 그 대안보다 이 배분을 택한 이유**를
먼저 제시한다. 이어서 기준일과 출처, 하방에서 달라지는 손익, 보유 변경 비용, 판단을 바꿀
가격·공시·지출 조건을 설명한다. 보유가 불완전하면 목표 비중만 제시한다.
`blocked_input`과 `infeasible`에서는 입력이나 제약을 다시 확인한다. 역사적 낙폭은 과거
진단이고 시나리오 손익은 가정이다. 성과 주장은 당시 저장한 판단의 사후 평가와 검증 범위를 따른다.

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

기존 v1 판단과 점수 배분은 [과거 보고서 재현 절차](references/legacy_allocation.md)를 따른다.
