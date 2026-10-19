#!/usr/bin/env python3
"""Build decision.json for the 2026-10-19 S&P 500 research portfolio.

The weights below are the session model's explicit judgment. This script only
assembles that judgment with its sources, VOO look-through and risk figures so
the decision can be reproduced and audited.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
# 생성 시각은 실행 시점의 실제 UTC 시각을 쓴다. 첫 스냅샷은 미래 시각을 고정값으로 넣어 대체됐다.
CREATED_AT = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
INPUT_CUTOFF = "2026-10-19T07:47:30Z"
# 웹 출처는 정확한 조회 시각을 남기지 않았다. 07:47:39Z에 확인한 시각보다 앞서 조회했으므로 이 상한값을 쓴다.
WEB_RETRIEVED_UPPER_BOUND = "2026-10-19T07:47:30Z"
PRICE_AS_OF = "2026-10-16T20:00:00Z"
SNAPSHOT_AS_OF = "2026-10-19T07:34:00Z"
SPY_HOLDINGS_AS_OF = "2026-10-15T00:00:00Z"

WEIGHTS = {"VOO": 0.74, "ADBE": 0.07, "ADSK": 0.05, "HIG": 0.04}
CASH_WEIGHT = 0.10
LIQUIDITY_WEIGHT = 0.05

# GOOG/GOOGL 같은 복수 상장 클래스는 같은 발행사로 묶는다.
ISSUER_ALIASES = {
    "GOOG": "GOOGL", "FOX": "FOXA", "NWS": "NWSA", "BRK-B": "BRK", "BF-B": "BF",
}


def source(sid, provider, reference, as_of, available_at, retrieved_at, max_age_days, **extra):
    return {
        "id": sid, "provider": provider, "reference": reference, "status": "ok",
        "as_of": as_of, "available_at": available_at, "retrieved_at": retrieved_at,
        "max_age_days": max_age_days, **extra,
    }


SOURCES = [
    source("yahoo_close", "Yahoo Finance (yfinance)", "regular market close via yfinance Ticker.info / history",
           PRICE_AS_OF, PRICE_AS_OF, "2026-10-19T07:34:10Z", 5,
           note="2026-10-16(금) 종가. 2026-10-19 미국 장 시작 전 조회."),
    source("yahoo_fundamentals", "Yahoo Finance (yfinance)", "portfolios/sp500_20261019/investor_source_data.json",
           SNAPSHOT_AS_OF, SNAPSHOT_AS_OF, "2026-10-19T07:34:10Z", 120,
           note="현재 스냅샷. 재무 결산일은 종목마다 다르며 공시 원문 대조는 아래 1차 출처로 일부만 수행."),
    source("ssga_spy_holdings", "State Street Global Advisors", "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx",
           SPY_HOLDINGS_AS_OF, SPY_HOLDINGS_AS_OF, "2026-10-19T07:22:29Z", 10,
           note="SPY 보유 목록. VOO 자체 보유 목록은 Vanguard 엔드포인트가 HTML만 반환해 확보하지 못했고, 같은 S&P 500 지수 추종을 근거로 VOO look-through 대용으로 사용."),
    source("vanguard_voo_fee", "Yahoo Finance (yfinance) fund profile", "VOO netExpenseRatio field",
           SNAPSHOT_AS_OF, SNAPSHOT_AS_OF, "2026-10-19T07:34:10Z", 120,
           note="운용사 원문이 아닌 Yahoo 펀드 프로필의 보수 필드(0.03%)."),
    source("adobe_8k_q3fy26", "Adobe Inc. (SEC Form 8-K Exhibit 99.1)", "https://www.sec.gov/Archives/edgar/data/796343/000079634326000147/adbeex991q326.htm",
           "2026-08-28T00:00:00Z", "2026-09-10T20:05:00Z", WEB_RETRIEVED_UPPER_BOUND, 120),
    source("autodesk_q2fy27", "Autodesk newsroom (company)", "https://adsknews.autodesk.com/en/?p=59702",
           "2026-07-31T00:00:00Z", "2026-08-27T20:05:00Z", WEB_RETRIEVED_UPPER_BOUND, 120,
           note="회사 뉴스룸의 실적 요약. investors.autodesk.com 원 보도자료는 HTTP 403으로 직접 조회하지 못함."),
    source("hartford_q2_2026", "The Hartford investor relations", "https://ir.thehartford.com/news/news-details/2026/The-Hartford-Reports-Strong-Second-Quarter-2026-Financial-Results/",
           "2026-06-30T00:00:00Z", "2026-07-23T20:05:00Z", WEB_RETRIEVED_UPPER_BOUND, 130,
           note="분기 공시 주기와 약 4주의 발표 지연을 고려해 130일 허용. 3분기 실적은 10월 하순 예정."),
    source("intuit_fy27_guidance_news", "24/7 Wall St. (secondary news)", "https://247wallst.com/investing/2026/08/26/intuit-sinks-12-as-ai-disruption-fears-spread-from-turbotax-to-quickbooks-adobe-and-servicenow-drop-3/",
           "2026-08-26T00:00:00Z", "2026-08-26T00:00:00Z", WEB_RETRIEVED_UPPER_BOUND, 120,
           note="2차 보도. 회사 원문 가이던스는 직접 대조하지 못함."),
    source("fred_dgs3mo", "Federal Reserve Bank of St. Louis (FRED DGS3MO)", "https://fred.stlouisfed.org/series/dgs3mo",
           "2026-10-15T00:00:00Z", "2026-10-16T21:00:00Z", WEB_RETRIEVED_UPPER_BOUND, 7,
           note="3개월 국채 4.28%(2026-10-15). 검색 결과로 확인했고 FRED 원본 표는 열람하지 않음."),
    source("predict_snapshot", "This repository: predict skill", "portfolios/sp500_20261019/sp500_predict.json",
           "2026-10-19T07:32:53Z", "2026-10-19T07:32:53Z", "2026-10-19T07:32:53Z", 3),
    source("risk_snapshot", "This repository: build_risk_snapshot.py", "portfolios/sp500_20261019/sp500_risk.json",
           PRICE_AS_OF, PRICE_AS_OF, "2026-10-19T07:36:33Z", 5),
    source("independent_analyses", "This repository: 3 isolated investor-perspective agents", "portfolios/sp500_20261019/investor_analyses.json",
           "2026-10-19T07:43:08Z", "2026-10-19T07:43:08Z", "2026-10-19T07:43:08Z", 3),
]


def quote(price):
    return {"value": price, "currency": "USD", "as_of": PRICE_AS_OF, "source_id": "yahoo_close"}


def voo_holdings(sector_by_ticker):
    frame = pd.read_excel(HERE / "raw" / "ssga_spy_holdings.xlsx", header=4)
    frame = frame[frame["Ticker"].notna() & frame["Weight"].notna()].copy()
    frame["Ticker"] = frame["Ticker"].astype(str).str.strip().str.replace(".", "-", regex=False)
    frame = frame[frame["Ticker"].str.match(r"^[A-Z][A-Z\-]*$")]
    holdings = [
        {
            "ticker": row.Ticker,
            "issuer": ISSUER_ALIASES.get(row.Ticker, row.Ticker),
            "sector": sector_by_ticker.get(row.Ticker) or "Unknown",
            "weight": round(float(row.Weight) / 100.0, 8),
        }
        for row in frame.itertuples()
    ]
    return sorted(holdings, key=lambda item: -item["weight"])


def thesis(**fields):
    return fields


def build_assets(prices, sector_by_ticker):
    holdings = voo_holdings(sector_by_ticker)
    top10 = sum(h["weight"] for h in holdings[:10])
    tech = sum(h["weight"] for h in holdings if h["sector"] == "Technology")
    assets = [
        {
            "ticker": "VOO", "asset_type": "etf", "weight": WEIGHTS["VOO"], "calendar": "XNYS",
            "quote": quote(prices["VOO"]),
            "selection_reason": "S&P 500 전체를 0.03% 보수로 보유하는 핵심 자산. 독립 분석에서 집중 매수할 만큼 강한 개별 종목 근거가 적어 지수 노출을 기본으로 둔다.",
            "thesis": thesis(
                rationale="개별 종목 30개 중 세 관점이 모두 긍정인 종목이 없고 대부분 confidence 50~60이었다. 이런 근거로 지수를 대체하기보다 저비용 지수를 핵심으로 두고, 근거가 상대적으로 나은 소수 종목만 위성으로 더한다.",
                price_assumptions="후행 P/E 약 24.2배(Yahoo)로 싸지 않다. 기대수익률 수치는 제시하지 않으며, 장기 보유 시 구성 기업의 이익 성장과 배당에 의존한다는 정성 가정만 둔다.",
                downside=f"상위 10개 비중 {top10:.1%}, 기술 섹터 {tech:.1%}로 AI 관련 대형주에 집중돼 있다. 이익 기대가 꺾이면 지수 전체가 큰 폭으로 재평가될 수 있다.",
                counterevidence="AI 투자 회수 지연이 대형 기술주 이익 하향으로 이어지거나, 지수 P/E가 높은 상태에서 장기 금리가 크게 오르면 핵심 비중 판단을 재검토한다.",
                review_trigger="SPY 기준 고점 대비 -20% 하락, 지수 후행 P/E 28배 초과, 또는 정기 검토일.",
                sizing_reason="개별 종목 근거가 약한 상황에서 분산 비레버리지 ETF가 가장 근거가 단단한 선택이다. 위성 16%와 현금 10%를 뺀 나머지를 배정했다.",
                alternative="SPY는 같은 지수에 보수 0.0945%로 더 비싸 VOO를 택했다. 동일가중 ETF는 이번 판단에서 독립 분석하지 않았다.",
                missing_evidence_impact="VOO 자체 보유 목록 대신 SPY 보유 목록(2026-10-15)을 대용으로 써서 look-through가 근사치다. 세 관점 중 하나만 긍정(버핏)이지만 나머지 둘도 부정이 아니라 가격 부담을 이유로 한 중립이다.",
                facts=[
                    {"text": "VOO 순보수 0.03%, SPY 0.0945%(Yahoo 펀드 프로필).", "source_refs": ["vanguard_voo_fee"]},
                    {"text": f"S&P 500 대용 보유 목록 503개, 상위 10개 {top10:.1%}, 기술 섹터 {tech:.1%}.", "source_refs": ["ssga_spy_holdings", "predict_snapshot"]},
                    {"text": "VOO 2026-10-16 종가 701.61달러, 1년 수익률 약 +16.8%(배당 조정 가격 기준).", "source_refs": ["yahoo_close"]},
                    {"text": "독립 분석: 버핏 bullish 50, 린치 neutral 50, 피셔 neutral 47.", "source_refs": ["independent_analyses"]},
                ],
            ),
            "etf": {
                "index": "S&P 500", "expense_ratio": 0.0003, "leverage": 1, "diversified": True,
                "concentration": f"503 holdings; top 10 = {top10:.1%}; Technology = {tech:.1%} (SPY holdings proxy)",
                "source_id": "ssga_spy_holdings", "holdings_as_of": SPY_HOLDINGS_AS_OF,
                "holdings_complete": False, "holdings": holdings,
            },
        },
        {
            "ticker": "ADBE", "asset_type": "stock", "weight": WEIGHTS["ADBE"], "calendar": "XNAS",
            "issuer": "ADBE", "sector": "Technology", "quote": quote(prices["ADBE"]),
            "selection_reason": "버핏·린치 관점이 독립적으로 긍정. 13% 매출 성장과 상향된 가이던스 대비 비-GAAP EPS 약 10배로 가격 매력이 위성 후보 중 가장 크다.",
            "thesis": thesis(
                rationale="크리에이티브·문서 소프트웨어의 전환 비용과 높은 현금 창출(영업마진 약 35%, 연 FCF 약 98억 달러)이 유지되는데 주가는 2년 고점 대비 약 56% 하락했다. 시장은 생성형 AI가 제품 가치를 대체할 위험을 크게 반영하고 있다고 본다(추론).",
                price_assumptions="245.2달러는 FY2026 비-GAAP EPS 가이던스 24.45~24.50달러의 약 10배, GAAP 18.12~18.17달러의 약 13.5배다. 이익이 유지되기만 해도 현재 배수가 과도하게 낮다는 가정이며, 목표가는 제시하지 않는다.",
                downside="AI 네이티브 경쟁으로 구독 갱신과 가격이 약해지면 이익과 배수가 함께 내려갈 수 있다. CEO 승계 진행 중이고 CFO가 임시 체제다. 60일 연환산 변동성 약 40%.",
                counterevidence="ARR 성장률이 한 자릿수 초반으로 떨어지거나, 연간 가이던스가 하향되거나, 승계 과정에서 전략 혼선이 드러나면 가설을 다시 본다.",
                review_trigger="4분기 실적 발표(12월), CEO 교체 시점, 종가 기준 매입가 대비 -25%.",
                sizing_reason="ADSK와 상관 0.71, INTU와 0.71로 같은 'AI의 응용 소프트웨어 대체' 요인에 묶인다. 소프트웨어 합계를 12%로 제한하고 그중 가격 근거가 가장 강한 ADBE에 7%를 둔다.",
                alternative="INTU는 같은 요인인데 가이던스 둔화가 확인돼 제외했다. CRM은 린치만 긍정이고 ROIC 8%로 품질 근거가 약했다.",
                missing_evidence_impact="피셔 관점은 neutral(성장률 15% 미만)이며 data_quality가 partial이다. 연도별 주식 수 이력이 없어 자사주 매입의 희석 상쇄 효과는 직접 계산하지 못했다.",
                facts=[
                    {"text": "Q3 FY2026 매출 67.6억 달러(+13%), 영업현금흐름 25.2억 달러, ARR 275.0억 달러, RPO 221.6억 달러(67% 단기).", "source_refs": ["adobe_8k_q3fy26"]},
                    {"text": "FY2026 매출 가이던스 265.76억~266.26억 달러, 비-GAAP EPS 24.45~24.50달러, GAAP 18.12~18.17달러.", "source_refs": ["adobe_8k_q3fy26"]},
                    {"text": "보도자료에 CEO 승계 언급과 임시 CFO 표기가 있다. 교체 시점은 보도자료에서 확인하지 못했다.", "source_refs": ["adobe_8k_q3fy26"]},
                    {"text": "2026-10-16 종가 245.2달러, 2년 고점(2024-12-06) 대비 약 -55.7%.", "source_refs": ["yahoo_close"]},
                    {"text": "독립 분석: 버핏 bullish 50, 린치 bullish 60, 피셔 neutral 55.", "source_refs": ["independent_analyses"]},
                ],
            ),
        },
        {
            "ticker": "ADSK", "asset_type": "stock", "weight": WEIGHTS["ADSK"], "calendar": "XNAS",
            "issuer": "ADSK", "sector": "Technology", "quote": quote(prices["ADSK"]),
            "selection_reason": "린치·피셔 관점이 독립적으로 긍정. 최근 분기 매출 +16%와 연간 가이던스 상향으로 성장 지속의 근거가 1차 자료로 확인된다.",
            "thesis": thesis(
                rationale="설계·건설 소프트웨어의 높은 전환 비용과 매출총이익률 약 91%, R&D 비중 약 23%로 피셔식 재투자가 확인된다. 건설(AECO) 수요와 갱신이 성장을 이끌었다.",
                price_assumptions="239.9달러는 FY2027 비-GAAP EPS 가이던스 12.52~12.60달러의 약 19배다. 후행 GAAP P/E는 약 31배로 비싸 보이지만 비-GAAP 기준은 성장률 대비 합리적이라는 가정이다. 비-GAAP와 GAAP 차이(주식보상 등)는 위험 요인으로 남긴다.",
                downside="D/E 약 1.10으로 부채가 있고 MaintainX 인수 통합 위험이 있다. 건설 경기 둔화나 AI 설계 도구와의 경쟁이 성장률을 낮출 수 있다. 60일 연환산 변동성 약 38%.",
                counterevidence="매출 성장률이 10% 아래로 떨어지거나 billings 가이던스가 하향되면 재검토한다.",
                review_trigger="3분기 실적 발표(11월 하순), 종가 기준 매입가 대비 -25%.",
                sizing_reason="ADBE와 같은 소프트웨어 요인이라 합계 12% 안에서 5%로 둔다. 가격 근거가 ADBE보다 약해 더 작게 둔다.",
                alternative="VEEV는 피셔만 긍정이고 후행 P/E 약 51배로 가격 부담이 더 컸다.",
                missing_evidence_impact="버핏 관점은 가격 부담(P/B 14.8배)으로 neutral이다. 원 보도자료 페이지가 403이라 회사 뉴스룸 요약으로 수치를 확인했고, FCF와 영업마진은 1차 자료로 대조하지 못했다.",
                facts=[
                    {"text": "Q2 FY2027 매출 20.5억 달러(+16%), 비-GAAP EPS 3.30달러, billings 18.5억 달러(+10%).", "source_refs": ["autodesk_q2fy27"]},
                    {"text": "FY2027 매출 가이던스 82.95억~83.45억 달러, 비-GAAP EPS 12.52~12.60달러, billings 85.75억~86.50억 달러로 상향.", "source_refs": ["autodesk_q2fy27"]},
                    {"text": "Yahoo 스냅샷 기준 매출총이익률 약 91%, R&D 16.4억 달러(매출의 약 22.8%), D/E 약 1.10.", "source_refs": ["yahoo_fundamentals"]},
                    {"text": "독립 분석: 버핏 neutral 50, 린치 bullish 55, 피셔 bullish 64.", "source_refs": ["independent_analyses"]},
                ],
            ),
        },
        {
            "ticker": "HIG", "asset_type": "stock", "weight": WEIGHTS["HIG"], "calendar": "XNYS",
            "issuer": "HIG", "sector": "Financial Services", "quote": quote(prices["HIG"]),
            "selection_reason": "버핏·린치 관점이 독립적으로 긍정하고, 변동성이 낮으며 VOO·소프트웨어와 상관이 거의 없어 실제 분산 효과가 있다.",
            "thesis": thesis(
                rationale="기업보험 중심 손해보험사로 후행 P/E 약 9.6배, 핵심이익 ROE 18.7%, 순이익이 2022~2025년 매년 증가했다. 새 42억 달러 자사주 매입 승인으로 주주환원이 이어진다.",
                price_assumptions="135.12달러는 AOCI 제외 주당순자산 78.91달러의 약 1.7배, 후행 P/E 약 9.6배다. 보험 사이클이 완만하게 둔화해도 현재 배수가 이를 일부 반영한다는 가정이며 목표가는 제시하지 않는다.",
                downside="Business Insurance 합산비율이 87.0에서 91.4로 악화됐고, 일반배상·상업용 자동차 준비금이 유리한 환입을 일부 상쇄했다. 연성 시장 진입과 재해 손실이 겹치면 이익이 정점에서 내려올 수 있다.",
                counterevidence="3분기에 불리한 준비금 적립(adverse development)이 확대되거나 underlying 합산비율이 90을 넘으면 비중을 줄이거나 제외한다.",
                review_trigger="3분기 실적 발표(10월 하순 예정), 연말 준비금 검토.",
                sizing_reason="준비금 추세 악화라는 반대 근거가 있어 4%로 작게 둔다. 변동성 약 19.5%, VOO와 상관 -0.07로 포트폴리오 변동성 기여가 작다.",
                alternative="CINF와 ALL은 같은 업종이지만 독립 분석에서 긍정 관점이 없었다. 현금 비중 확대와도 비교했으며, 4%는 주식 위험을 일부 분산하는 대안으로 판단했다.",
                missing_evidence_impact="피셔 관점은 업종 특성상 기준이 맞지 않아 abstain(insufficient)이다. 이는 부정 신호가 아니라 틀이 맞지 않는 것이며, 버핏·린치 근거와 1차 공시로 대신 확인했다.",
                facts=[
                    {"text": "2026년 2분기 핵심이익 9.45억 달러(주당 3.42달러), 순이익 13억 달러(주당 4.68달러).", "source_refs": ["hartford_q2_2026"]},
                    {"text": "Business Insurance 합산비율 91.4(전년 87.0), underlying 89.3(전년 88.0). Personal Insurance 90.1(전년 94.1).", "source_refs": ["hartford_q2_2026"]},
                    {"text": "유리한 전기 준비금 환입(PYD) 1.11억 달러로 전년 1.87억 달러에서 감소. 일반배상·상업용 자동차 준비금이 일부 상쇄.", "source_refs": ["hartford_q2_2026"]},
                    {"text": "AOCI 제외 주당순자산 78.91달러, 12개월 핵심이익 ROE 18.7%, 2026-08-01부터 42억 달러 자사주 매입 승인.", "source_refs": ["hartford_q2_2026"]},
                    {"text": "독립 분석: 버핏 bullish 55, 린치 bullish 55, 피셔 abstain 25(insufficient).", "source_refs": ["independent_analyses"]},
                ],
            ),
        },
    ]
    excluded = {
        "SPY": "벤치마크. 같은 지수를 더 낮은 보수로 보유할 수 있어 VOO를 택했다.",
        "INTU": "버핏·피셔가 긍정했지만 FY2027 매출 성장 가이던스 9~10%, TurboTax +2~3%, 의도적 가격 인하가 보도돼 가격결정력 가설이 흔들린다. ADBE·ADSK와 같은 요인이라 독립 근거 없이 집중도만 높인다. 회사 원문 가이던스 대조 후 재검토 대상.",
        "MSFT": "피셔가 74로 가장 강하게 긍정했지만 버핏·린치는 가격(P/E 29.5)과 capex 급증으로 중립. VOO 안에 약 6.0%가 이미 들어 있어 직접 추가는 집중을 키운다.",
        "CRM": "린치만 긍정. ROIC 8%, D/E 1.10으로 품질 근거가 약하다.",
        "VEEV": "피셔만 긍정. 후행 P/E 약 51배로 가격 근거가 약하다.",
        "EOG": "predict 1위지만 세 관점 중 긍정이 없고 피셔는 부정. 에너지 이익이 유가 사이클에 좌우된다.",
        "MPC": "버핏·피셔 부정. 정유 마진 정점 가능성과 D/E 1.33.",
    }
    for ticker, reason in excluded.items():
        assets.append({
            "ticker": ticker,
            "asset_type": "etf" if ticker == "SPY" else "stock",
            "weight": 0, "calendar": "XNAS" if ticker in {"INTU", "MSFT"} else "XNYS",
            "quote": quote(prices[ticker]), "selection_reason": reason,
        })
    return assets


def risk_summary(risk, assets):
    vol, cor = risk["annualized_volatility"], risk["correlation"]
    weights = {a["ticker"]: a["weight"] for a in assets if a["weight"] > 0}
    variance = sum(
        weights[i] * weights[j] * vol[i] * vol[j] * cor[i][j]
        for i in weights for j in weights
    )
    return math.sqrt(variance)


def main():
    source_data = json.loads((HERE / "investor_source_data.json").read_text(encoding="utf-8"))
    predict = json.loads((HERE / "sp500_predict.json").read_text(encoding="utf-8"))
    risk = json.loads((HERE / "sp500_risk.json").read_text(encoding="utf-8"))
    prices = {t: v["profile"]["regularMarketPrice"] for t, v in source_data["tickers"].items()}
    sector_by_ticker = {r["ticker"]: (r.get("metrics") or {}).get("sector") for r in predict["rankings"]}
    assets = build_assets(prices, sector_by_ticker)
    portfolio_vol = risk_summary(risk, assets)
    regime = risk["market_regime"]

    decision = {
        "schema_version": "portfolio_decision_v1",
        "decision_id": "sp500-20261019-core-satellite-r2",
        "previous_decision_id": "sp500-20261019-core-satellite",
        "revision_note": "판단과 비중은 동일하다. 첫 스냅샷의 created_at(08:10Z)과 일부 retrieved_at이 실제 시각보다 늦게 적힌 오류를 실제 파일 시각과 실행 시각으로 바로잡았다.",
        "analysis_date": "2026-10-19",
        "created_at": CREATED_AT,
        "input_cutoff": INPUT_CUTOFF,
        "author": "Claude Code session (claude-opus-5-5); investor perspectives by isolated Claude subagents (agent definition model alias: sonnet)",
        "base_currency": "USD",
        "benchmark": "SPY",
        "user_context": {
            "objective": "가정: 장기 복리 성과 극대화. 사용자가 목표를 별도로 확인하지 않았다.",
            "evaluation_horizon": "6개월 후 첫 사후 평가. 전략 자체는 장기 보유를 전제로 한다.",
            "spending_horizon": "미확인. 1~3년 안에 일부 인출 가능성을 배제하지 않는 가정.",
            "spending_currency": "USD",
            "required_amount": None,
            "risk_tolerance": "미확인. 주식형 하락(-30% 내외)을 견딜 수 있다고 가정하고 개별 종목 집중은 제한한다.",
            "holdings": "unknown",
            "liquidity_min_weight": LIQUIDITY_WEIGHT,
            "liquidity_basis": "assumption",
            "liquidity_reason": "지출 계획·금액·통화가 확인되지 않아 5%를 가정 준비금으로 둔다. 원화 지출이 필요하면 환전 비용과 환율 위험이 추가된다.",
        },
        "sources": SOURCES,
        "assets": assets,
        "constraints": {
            "max_stock_weight": 0.15,
            "max_diversified_etf_weight": 1,
            "max_direct_sector_weight": 0.35,
            "rationale": "저장소 기본 정책(개별 주식 15%, 직접 주식 섹터 35%, 분산 비레버리지 ETF 100%)을 그대로 사용했다. 사용자 한도가 확인되지 않았으며 이 수치가 최적이라고 주장하지 않는다. 소프트웨어 합계 12%는 상관 0.6~0.7을 근거로 스스로 둔 판단 한도다.",
        },
        "cash": {
            "weight": CASH_WEIGHT,
            "currency": "USD",
            "annual_rate": 0.0428,
            "liquidity_weight": LIQUIDITY_WEIGHT,
            "rationale": "가정 준비금 5%와 전략적 대기 5%.",
            "opportunity_cost": "3개월 국채 약 4.28%를 받는 대신 주식 장기 수익을 일부 포기한다. 지수 P/E 약 24배에서 이 기회비용은 평소보다 작다고 판단한다(추론).",
            "liquidity_reason": "지출 조건 미확인에 따른 가정 준비금.",
            "strategic_reason": "지수 집중도와 밸류에이션이 높고, 위성 종목(ADBE·HIG)의 실적·승계 이벤트가 3개월 안에 몰려 있어 분할 추가 여력을 남긴다.",
            "market_regime_reason": f"SPY 가격 규칙의 국면은 {regime['regime']}, 참고 현금 {regime['target_cash_weight']:.2%}. 최종 10%는 이 참고값과 거의 같으며 시장 급락 예측이 아니다.",
        },
        "evaluation": {
            "method": "initial_weights_buy_and_hold",
            "review_at": "2027-04-19T21:00:00Z",
            "dividends": "reinvested",
            "tax_basis": "pre_tax",
            "entry_cost_bps": 5,
            "exit_cost_bps": 5,
            "fx_cost_bps": 0,
            "cost_assumptions": "미국 무수수료 브로커에서 대형주·대형 ETF 체결 시 호가 스프레드와 슬리피지 약 5bp 가정. USD 기준이라 환전 비용 0으로 두었고, 원화 투자자의 환전·환율 효과는 평가에서 별도로 다룬다.",
            "review_trigger": "정기 검토일, HIG 3분기 실적, ADBE 4분기 실적·CEO 교체, ADSK 3분기 실적, SPY 고점 대비 -20%.",
        },
        "portfolio_notes": {
            "estimated_annualized_volatility": round(portfolio_vol, 4),
            "volatility_basis": "risk snapshot의 60일 이상 일간 수익률 공분산, 현금 변동성 0 가정. 미래 변동성이나 최대 손실의 상한이 아니다.",
        },
    }
    (HERE / "decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved decision.json; est. vol {portfolio_vol:.2%}; assets {len(assets)}")


if __name__ == "__main__":
    main()
