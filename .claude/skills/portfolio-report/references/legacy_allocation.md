# 기존 점수 배분 재현

`--decision-json` 없이 generate_portfolio_report.py를 실행하면 기존 경로다.
predict/investor/risk JSON, --top, --investors, --xlsx, --portfolio-json,
--output-dir 인자는 그대로 지원한다. JSON decision_mode는 legacy_score_allocation이다.

- 요청한 독립 관점이 모두 있어야 한다. 한 관점이라도 insufficient이면 제외한다.
- 과반 bullish 후보의 total_score × confidence × bullish 비율을 변동성과 양의 상관으로 조정한다.
- 종목 상한 15%, 섹터 상한 35%, 최소 2%를 적용한다.
- 시장 국면의 현금 목표가 하한이고 배분 후 잔액도 현금이 된다.
- 점수 환산값은 예상 수익률이 아니며 기존 methodology는 새 명시적 판단과 다르다.

과거 결과의 재현 계약이다. 새 추천은 decision_contract.md의 판단 경로를 사용한다.
이미 저장한 보고서에 새 방식으로 검증했다는 표시를 소급 추가하지 않는다.
