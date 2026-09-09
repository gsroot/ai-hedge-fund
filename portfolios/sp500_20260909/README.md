# S&P 500 연구 포트폴리오 · 2026-09-09

최종 목표 비중은 **주식 49.9%, USD 현금 50.1%**다. S&P 500 현재 구성 503개 전체를 hybrid 전략으로 분석하고, 상위 30개에 대해 버핏·린치·피셔 관점을 각각 독립적으로 산출했다. 금액과 개인 투자 조건은 지정되지 않아 비중으로만 구성했다.

| 종목 | 회사 | 비중 | 긍정 관점 | 핵심 판단과 위험 |
|---|---|---:|---|---|
| ADBE | Adobe | 15.0% | 버핏·린치·피셔 | 창작·문서 소프트웨어의 현금창출과 연구개발 투자. AI 경쟁과 고객 유지의 지속성은 미검증. |
| INCY | Incyte | 15.0% | 린치·피셔 | 다년 매출 성장, 연구개발을 뒷받침하는 현금. 제품 집중·특허·임상 위험. |
| NVDA | NVIDIA | 12.0% | 린치·피셔 | 가속컴퓨팅의 실제 매출 확대와 연구개발 투자. 고객 설비투자 주기·경쟁·가격 기대 위험. |
| GDDY | GoDaddy | 7.9% | 버핏·린치 | 도메인·웹서비스의 현금창출 개선. 성장 속도·차입·고객 갱신 확인 필요. |
| 현금 | USD 현금 | 50.1% | 해당 없음 | 시장 현금 목표와 편입·비중 제약에 따른 잔여 비중. |
| 합계 | | **100.0%** | | |

## 현금이 50.1%인 이유

SPY의 2026-09-08 종가까지 가격 규칙으로 계산한 국면은 `risk_on`, 시장 목표 현금은 **9.92%**다. 최종 현금이 더 많은 주된 이유는 편입 요건과 상한이다.

- 3개 관점 중 2개 이상이 긍정이고, 어느 관점도 `insufficient`가 아닌 종목만 남긴다.
- 이 조건을 통과한 종목은 ADBE, INCY, NVDA, GDDY의 4개다.
- 단일 종목 15%, 단일 섹터 35%, 최소 비중 2%를 적용한다. 0.1% 단위 비중 내림 후 기술주 34.9%, 헬스케어 15.0%가 남는다.
- HIG·TRV·TROW는 두 관점이 긍정이어도 피셔 관점에 필요한 보험·운용업 세부 자료가 부족해 제외됐다. 이는 기업이 나쁘다는 판단과 다르다.
- 부족한 근거를 임의 중립값으로 보충하거나 상한을 넘어 주식 비중을 채우지 않았다.

따라서 현금 50.1%를 시장 급락 예측으로 해석하면 안 된다. 주식 부분은 4개 종목·2개 섹터에 집중되어 있어 분산이 제한적이다.

## 데이터와 근거 수준

**직접 관찰:** 2026-09-09 수집. 503/503개 순위 산출, 독립 분석 90건, 위험 가격 30개 및 SPY 모두 2026-09-08까지 관측. 세 투자자 분석은 서로의 결론과 predict 점수 없이 원천 자료를 읽은 별도 Codex 에이전트가 수행했다. 투자자 본인의 의견이 아니라 해당 투자 철학을 적용한 LLM 판단이다.

**외부 출처:** 가격·재무는 Yahoo Finance 현재 스냅샷, 구성 종목은 [Wikipedia의 현재 표](https://en.wikipedia.org/wiki/List_of_S%26P_500_companies)를 사용했다. 503개 티커는 [State Street의 SPY 보유 목록](https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy)의 2026-09-04 자료와 전부 일치했다. ETF 보유 목록은 대조용이며 과거 지수 구성 이력의 증거는 아니다. [9월 21일 예정된 공식 지수 변경](https://press.spglobal.com/2026-09-04-Bloom-Energy,-Illumina,-and-Everpure-Set-to-Join-S-P-500-Others-to-Join-S-P-100,-S-P-MidCap-400,-and-S-P-SmallCap-600)은 미리 반영하지 않았다.

**대체 경로:** 최초 Wikipedia 준비도 감사는 HTTP 403으로 실패했다. 같은 페이지에 HTTP 요청 후 표를 읽는 방식으로 503개를 확보했다. 최초 실패 기록을 보존했으며, 이를 모든 provider가 처음부터 정상이라는 근거로 바꾸지 않았다.

**부분 확인:** [CF의 상반기 실적](https://www.cfindustries.com/newsroom/2026/1h-2026-earnings), [Phillips 66의 2분기 실적](https://investor.phillips66.com/financial-information/news-releases/news-release-details/2026/Phillips-66-Delivers-Strong-Second-Quarter-Results-and-Operating-Performance/default.aspx), [Micron의 회계 3분기 실적](https://investors.micron.com/news/press-release/2026/Micron-Technology-Inc--Reports-Record-Results-for-the-Third-Quarter-of-Fiscal-2026/default.aspx)을 일부 대조했다. CF·MU의 Yahoo FCF와 회사 발표 FCF는 정의·기간을 완전히 조정하지 못했고, PSX의 현금흐름에는 운전자본 효과가 있다. 전 종목 공시 원문 대조 완료를 뜻하지 않는다.

**추론:** 상대 순위, 독립 투자자 판단, 시장 국면, 현금 목표와 종목 비중은 휴리스틱이다. confidence는 판단 근거의 주관적 강도이며 성공 확률이 아니다. 단순 가격 규칙의 `risk_on`은 거시경제 전반에 대한 전망이 아니다.

**미검증:** 모든 기본 팩터는 `prior_only` / `unvalidated`다. 이 정확한 순위·독립 분석·위험 조정·상한 조합의 point-in-time 및 독립 OOS 성과는 없다. 뉴스는 순위를 차별화하지 않으며 완전한 이벤트 검토도 수행하지 않았다. 순위 점수 환산값을 기대수익률로 제시하지 않는다.

## 해석상 한계

- 조회일과 재무제표 결산일은 다르다. Yahoo 현재 스냅샷을 과거 공시 시점에 이용 가능했던 재무자료로 간주하지 않는다.
- 전체 유니버스에서 ROE 34개, FCF 33개, 매출 성장 1개, 섹터 1개가 누락됐다. 누락 값은 원천 스냅샷에 보존했다.
- P/E는 후행 값 우선이며 없으면 선행 값으로 대체된다. 상위 후보 IVZ는 선행 P/E다. 다른 기간의 배수를 동일하게 비교하면 안 된다.
- `debt_to_assets` 원천 파생 필드는 회계상 총자산 대비 부채비율이 아니므로 독립 판단에 해당 의미로 사용하지 않았다.
- 과거 공분산으로 추정한 전체 포트폴리오 연변동성은 약 **11.0%**다. USD 현금 변동성 0을 가정했으며, 미래 변동성이나 최대 손실의 상한이 아니다.
- 세금·원화 환율 변동·수수료·체결 슬리피지는 반영하지 않았다. 실제 거래·자금 이동은 수행하지 않았다.

## 검증과 산출물

- 비중 합계 100%, 종목·섹터 상한, 최소 비중, 실제 현금 ≥ 시장 현금 목표 검증 통과.
- 저장된 순위·독립 분석·위험 스냅샷에서 재계산한 비중이 최종 JSON과 일치.
- 위험 가격의 관측 범위·상관 대칭성·유효 변동성 및 입력 파일 해시 확인.
- 기존 `AllocationConstraintTests` 14개 통과. 새 제품·파이프라인 코드 변경은 없음.
- Agent OS doctor의 `PLUGIN_CAPABILITY_REGISTRY_DRIFT` 경고는 미해결이다. 애플리케이션 계산 검증 실패와는 별개다.
- 엑셀 4개 시트의 렌더·수식·저장값을 검증했다. Microsoft Excel 앱에서의 직접 실행은 별도 미수행.

주요 파일: `sp500_portfolio.json`, `sp500_predict.json`, `investor_analyses.json`, `sp500_risk.json`, `validation_summary.json`. 원천은 `investor_source_data.json`, `predict_input_metrics.json`, `risk_price_inputs.json`에 보존했다. 독립 분석 90건과 제외 사유는 엑셀 및 JSON에서 확인할 수 있다.

엑셀: [sp500_20260909_portfolio.xlsx](../../outputs/01a08599-dd56-71d0-8f8e-c239feafefd1/sp500_20260909_portfolio.xlsx)

이 자료는 교육·연구용 선별 결과이며 성과가 검증된 실전 운용안이나 개인별 투자 자문으로 취급하지 않는다.
