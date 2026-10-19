# S&P 500 연구 포트폴리오 · 2026-10-19

최종 목표 비중은 **VOO 74%, ADBE 7%, ADSK 5%, HIG 4%, USD 현금 10%**다. 판단 ID는
`sp500-20261019-core-satellite-r2`이고 상태는 `conditional`이다. 사용자의 금액·목표·지출·보유가
확인되지 않아 이를 가정으로 둔 추천이다. 추천을 포기한다는 뜻은 아니다.

| 자산 | 비중 | 긍정 관점 | 핵심 판단 | 가장 큰 위험 |
|---|---:|---|---|---|
| VOO | 74.0% | 버핏 | S&P 500 503개를 0.03% 보수로 보유. 개별 종목 근거가 지수를 대체할 만큼 강하지 않다. | 상위 10개 38.6%, 기술 38.4% 집중. 후행 P/E 약 24배. |
| ADBE | 7.0% | 버핏·린치 | FY2026 비-GAAP EPS 가이던스의 약 10배. 매출 +13%, 가이던스 상향. | 생성형 AI 대체, CEO 승계·임시 CFO. |
| ADSK | 5.0% | 린치·피셔 | 매출 +16%, 연간 가이던스 상향, 비-GAAP 약 19배. | D/E 약 1.1, 인수 통합, 건설 경기. |
| HIG | 4.0% | 버핏·린치 | 후행 P/E 약 9.6배, 핵심 ROE 18.7%. VOO와 상관 -0.07로 분산 효과. | Business Insurance 합산비율 87.0→91.4, 준비금 추세. |
| 현금 | 10.0% | 해당 없음 | 가정 준비금 5% + 전략적 대기 5%. 시장 규칙 참고값 9.53%와 거의 같다. | 3개월 국채 약 4.28% 대비 주식 기회비용. |

과거 공분산으로 추정한 포트폴리오 연변동성은 약 **10.9%**다(현금 변동성 0 가정). look-through
기준 기술 섹터 합계는 **40.4%**, 단일 발행사 최대 노출은 ADBE 7.1%다.

## 왜 이 구성인가

- 30개 후보 중 **세 관점이 모두 긍정인 종목은 없었다.** 두 관점이 긍정인 종목은 ADBE, ADSK,
  INTU, HIG이고 confidence는 대부분 50~60이다. 이 정도 근거로 지수를 대체하지 않고 저비용 지수를
  핵심으로 둔 뒤 위성 종목을 더했다.
- 이전(2026-09-09) 판단의 현금 50.1%는 편입 규칙과 상한이 만든 잔여였다. 이번에는 판단 계약에 따라
  잔여를 현금으로 자동 확정하지 않고 분산 ETF와 다시 비교했다.
- predict 상위권을 채운 **에너지·정유 8개는 세 관점 중 긍정이 하나도 없었다.** 피셔는 8개 모두
  부정이다. 정량 순위와 독립 판단이 크게 갈린 지점이다.
- 소프트웨어 3개(ADBE·ADSK·INTU)는 서로 상관 0.64~0.71로 같은 위험 요인이다. 합계를 12%로
  제한했다.

### INTU를 제외한 이유

버핏·피셔가 긍정했지만, 두 관점은 과거 매출 CAGR을 근거로 삼았고 가이던스 정보를 보지 못했다.
2차 보도에 따르면 FY2027 매출 성장 가이던스는 9~10%, TurboTax는 +2~3%이고 회사가 의도적으로 가격을
낮추고 있다. 이는 "가격결정력이 해자"라는 가설의 핵심과 충돌한다. ADBE·ADSK와 같은 요인이라 독립
근거 없이 집중도만 높인다고 판단했다. 회사 원문 가이던스를 대조한 뒤 재검토할 대상이다.

## 데이터와 근거 수준

**직접 관찰:** 2026-10-19 수집. 503/503개 순위 산출, 제외 0개. 독립 분석 96건(32개 자산 × 3관점).
위험 가격 32개 모두 2026-10-16 종가까지 관측. 세 관점은 predict 점수와 서로의 결론을 보지 못하게
입력을 분리한 별도 Claude 에이전트가 수행했다. 투자자 본인의 의견이 아니라 해당 철학을 적용한
LLM 판단이다.

**외부 출처:**
- 구성 종목: [Wikipedia 현재 표](https://en.wikipedia.org/wiki/List_of_S%26P_500_companies) 503개가
  [SSGA SPY 보유 목록](https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx)(2026-10-15)과 전부 일치.
  ETF 보유 목록은 대조용이며 공식 지수 구성 이력의 증거는 아니다.
- [Adobe Q3 FY2026 8-K](https://www.sec.gov/Archives/edgar/data/796343/000079634326000147/adbeex991q326.htm),
  [Autodesk Q2 FY2027 뉴스룸](https://adsknews.autodesk.com/en/?p=59702),
  [The Hartford Q2 2026 IR](https://ir.thehartford.com/news/news-details/2026/The-Hartford-Reports-Strong-Second-Quarter-2026-Financial-Results/)
- [INTU 가이던스 보도(2차)](https://247wallst.com/investing/2026/08/26/intuit-sinks-12-as-ai-disruption-fears-spread-from-turbotax-to-quickbooks-adobe-and-servicenow-drop-3/),
  [FRED DGS3MO](https://fred.stlouisfed.org/series/dgs3mo)(검색 결과로 확인, 원본 표 미열람)

**대체 경로:**
- provider readiness의 `wikipedia_sp500`은 `unavailable`이었다. 같은 페이지를 User-Agent 헤더로 직접
  요청해 503개를 얻고 predict의 당일 캐시에 넣었다. 그래서 predict 결과의 `universe.source`는
  `daily_cache`로 표시된다.
- VOO 자체 보유 목록은 Vanguard 엔드포인트가 HTML만 반환해 얻지 못했다. 같은 지수를 추종하는
  SPY 보유 목록을 대용으로 쓰고 `holdings_complete: false`로 기록했다.
- Autodesk IR 원 보도자료는 HTTP 403이라 회사 뉴스룸 요약으로 대신했다.

**추론:** 독립 판단의 종합, 소프트웨어 합계 12% 한도, 종목별 비중, 현금 10%는 판단이다.
confidence는 근거의 주관적 강도이며 성공 확률이 아니다.

**미검증:** 모든 기본 팩터는 `prior_only` / `unvalidated`다. 이 판단 방식의 point-in-time·OOS
성과는 없다. 뉴스는 순위를 바꾸지 않았다. 점수 환산값을 기대수익률로 쓰지 않았다.

## 기록 정정

첫 스냅샷 `sp500-20261019-core-satellite`는 `created_at`(08:10Z)과 일부 웹 출처의 `retrieved_at`이
실제 시각보다 늦게 적힌 상태로 저장됐다. 비중과 판단은 같고, 실제 파일 시각과 실행 시각으로 바로잡은
`-r2`가 이를 대체한다(`previous_decision_id`로 연결). 정확한 조회 시각을 남기지 않은 웹 출처는 확인 가능한
상한값(07:47:30Z)을 썼다. 첫 스냅샷은 삭제하지 않고 보존했다.

## 해석상 한계

- Yahoo 현재 스냅샷을 과거 공시 시점의 자료로 간주하지 않는다. 결산일은 종목마다 다르다.
- HIG의 3분기 실적(10월 하순 예정), ADSK 3분기(11월 하순), ADBE 4분기와 CEO 교체가 3개월 안에 몰려
  있다. 각 이벤트가 재검토 조건이다.
- 세금, 원화 환율, 환전 비용은 반영하지 않았다. 원화 기준 투자자는 USD/KRW 변동이 수익에 더해진다.
- 실제 거래·자금 이동은 수행하지 않았다.

## 산출물

- 판단: `decision.json`(생성: `build_decision.py`), 스냅샷: `../decisions/sp500-20261019-core-satellite-r2/`
- 보고서: `sp500_portfolio.json`, `sp500_portfolio.txt`, `sp500_portfolio.xlsx`
- 원천: `sp500_predict.json`, `investor_source_data.json`, `investor_{buffett,lynch,fisher}.json`,
  `investor_analyses.json`, `sp500_risk.json`, `sp500_constituents_20261019.json`,
  `ssga_membership_crosscheck.json`, `raw/ssga_spy_holdings.xlsx`
- 첫 사후 평가 예정일: 2027-04-19 (`evaluate_decision.py`, 최초 비중 매수 후 보유 기준)

이 자료는 교육·연구용 의사결정 지원 결과이며, 성과가 검증된 실전 운용안이나 개인별 투자 자문이 아니다.
