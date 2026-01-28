"""
Yahoo Finance / 한국 주식 데이터 조회 모듈

재무 지표, 가격, 뉴스, 내부자 거래, 인덱스 구성종목 데이터를 수집합니다.
모든 API 호출은 rate_limiter의 안전한 래퍼를 통해 수행되며,
결과는 cache 모듈을 통해 파일 기반 캐싱됩니다.

한국 주식(6자리 숫자 종목코드)은 자동으로 DART + PyKRX로 라우팅됩니다.
"""
import os
import json
from datetime import datetime

import pandas as pd

from config import CACHE_DIR, CACHE_ENABLED
from cache import _get_cache_path, _read_cache, _write_cache, cache_stats
from rate_limiter import (
    safe_get_ticker_info,
    safe_get_ticker_news,
    safe_get_insider_transactions,
    safe_get_ticker_history,
    safe_get_financials,
    safe_get_balance_sheet,
    safe_batch_download,
)
from ticker_utils import is_korean_ticker, normalize_korean_ticker, is_korean_index

# ============================================================================
# 인덱스 종목 리스트 (폴백용 하드코딩)
# ============================================================================

FALLBACK_SP500 = """MMM,AOS,ABT,ABBV,ACN,ADBE,AMD,AES,AFL,A,APD,ABNB,AKAM,ALB,ARE,ALGN,ALLE,LNT,ALL,GOOGL,MO,AMZN,AMCR,AEE,AEP,AXP,AIG,AMT,AWK,AMP,AME,AMGN,APH,ADI,AON,APA,APO,AAPL,AMAT,APTV,ACGL,ADM,ANET,AJG,AIZ,T,ATO,ADSK,ADP,AZO,AVB,AVY,AXON,BKR,BALL,BAC,BAX,BDX,BBY,TECH,BIIB,BLK,BX,BK,BA,BKNG,BSX,BMY,AVGO,BR,BRO,BLDR,BG,BXP,CHRW,CDNS,CZR,CPT,CPB,COF,CAH,KMX,CCL,CARR,CAT,CBOE,CBRE,CDW,COR,CNC,CNP,CF,CRL,SCHW,CHTR,CVX,CMG,CB,CHD,CI,CINF,CTAS,CSCO,C,CFG,CLX,CME,CMS,KO,CTSH,COIN,CL,CMCSA,CAG,COP,ED,STZ,CEG,COO,CPRT,GLW,CPAY,CTVA,CSGP,COST,CTRA,CRWD,CCI,CSX,CMI,CVS,DHR,DRI,DDOG,DVA,DAY,DECK,DE,DELL,DAL,DVN,DXCM,FANG,DLR,DG,DLTR,D,DPZ,DASH,DOV,DOW,DHI,DTE,DUK,DD,EMN,ETN,EBAY,ECL,EIX,EW,EA,ELV,EMR,ENPH,ETR,EOG,EPAM,EQT,EFX,EQIX,EQR,ERIE,ESS,EL,EG,EVRG,ES,EXC,EXE,EXPE,EXPD,EXR,XOM,FFIV,FDS,FICO,FAST,FRT,FDX,FIS,FITB,FSLR,FE,FI,F,FTNT,FTV,FOXA,FOX,BEN,FCX,GRMN,IT,GE,GEHC,GEV,GEN,GNRC,GD,GIS,GM,GPC,GILD,GPN,GL,GDDY,GS,HAL,HIG,HAS,HCA,DOC,HSIC,HSY,HPE,HLT,HOLX,HD,HON,HRL,HST,HWM,HPQ,HUBB,HUM,HBAN,HII,IBM,IEX,IDXX,ITW,INCY,IR,PODD,INTC,ICE,IFF,IP,IPG,INTU,ISRG,IVZ,INVH,IQV,IRM,JBHT,JBL,JKHY,J,JNJ,JCI,JPM,KVUE,KDP,KEY,KEYS,KMB,KIM,KMI,KKR,KLAC,KHC,KR,LHX,LH,LRCX,LW,LVS,LDOS,LEN,LII,LLY,LIN,LYV,LKQ,LMT,L,LOW,LULU,LYB,MTB,MPC,MKTX,MAR,MMC,MLM,MAS,MA,MTCH,MKC,MCD,MCK,MDT,MRK,META,MET,MTD,MGM,MCHP,MU,MSFT,MAA,MRNA,MHK,MOH,TAP,MDLZ,MPWR,MNST,MCO,MS,MOS,MSI,MSCI,NDAQ,NTAP,NFLX,NEM,NWSA,NWS,NEE,NKE,NI,NDSN,NSC,NTRS,NOC,NCLH,NRG,NUE,NVDA,NVR,NXPI,ORLY,OXY,ODFL,OMC,ON,OKE,ORCL,OTIS,PCAR,PKG,PANW,PARA,PH,PAYX,PAYC,PYPL,PNR,PEP,PFE,PCG,PM,PSX,PNW,PNC,POOL,PPG,PPL,PFG,PG,PGR,PLD,PRU,PEG,PTC,PSA,PHM,QRVO,PWR,QCOM,DGX,RL,RJF,RTX,O,REG,REGN,RF,RSG,RMD,RVTY,ROK,ROL,ROP,ROST,RCL,SPGI,CRM,SBAC,SLB,STX,SRE,NOW,SHW,SPG,SWKS,SJM,SW,SNA,SOLV,SO,LUV,SWK,SBUX,STT,STLD,STE,SYK,SMCI,SYF,SNPS,SYY,TMUS,TROW,TTWO,TPR,TRGP,TGT,TEL,TDY,TFX,TER,TSLA,TXN,TXT,TMO,TJX,TSCO,TT,TDG,TRV,TRMB,TFC,TYL,TSN,USB,UBER,UDR,ULTA,UNP,UAL,UPS,URI,UNH,UHS,VLO,VTR,VLTO,VRSN,VRSK,VZ,VRTX,VIAV,V,VST,VMC,WRB,GWW,WAB,WBA,WMT,DIS,WBD,WM,WAT,WEC,WFC,WELL,WST,WDC,WY,WMB,WTW,WYNN,XEL,XYL,YUM,ZBRA,ZBH,ZTS"""

FALLBACK_NASDAQ100 = """AAPL,ABNB,ADBE,ADI,ADP,ADSK,AEP,AMAT,AMGN,AMZN,ANSS,ARM,ASML,AVGO,AZN,BIIB,BKNG,BKR,CDNS,CDW,CEG,CHTR,CMCSA,COST,CPRT,CRWD,CSCO,CSGP,CSX,CTAS,CTSH,DDOG,DLTR,DXCM,EA,EXC,FANG,FAST,FTNT,GEHC,GFS,GILD,GOOG,GOOGL,HON,IDXX,ILMN,INTC,INTU,ISRG,KDP,KHC,KLAC,LIN,LRCX,LULU,MAR,MCHP,MDB,MDLZ,MELI,META,MNST,MRNA,MRVL,MSFT,MU,NFLX,NVDA,NXPI,ODFL,ON,ORLY,PANW,PAYX,PCAR,PDD,PEP,PYPL,QCOM,REGN,ROP,ROST,SBUX,SMCI,SNPS,TEAM,TMUS,TSLA,TTD,TTWO,TXN,VRSK,VRTX,WBD,WDAY,XEL,ZS"""


# ============================================================================
# 내부자 거래 데이터
# ============================================================================

def _fetch_insider_trades_yf(ticker: str, limit: int = 100) -> list:
    """
    Yahoo Finance에서 내부자 거래 데이터 가져오기

    주요 기능:
    - 최대 100건의 내부자 거래 조회
    - 주당 거래 가격(transaction_price_per_share) 자동 계산
    - transaction_date, ownership_type, filing_url 필드 포함
    - Rate limiting 재시도 로직 적용
    """
    try:
        insider_df = safe_get_insider_transactions(ticker)

        if insider_df is None or (hasattr(insider_df, 'empty') and insider_df.empty):
            return []

        trades = []
        for _, row in insider_df.head(limit).iterrows():
            shares = row.get("Shares")
            value = row.get("Value")

            # 주당 거래 가격 계산
            price_per_share = None
            if shares and value and shares != 0:
                try:
                    price_per_share = float(value) / float(shares)
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

            trades.append({
                "insider_name": row.get("Insider") or row.get("Name"),
                "insider_title": row.get("Position") or row.get("Title"),
                "transaction_type": row.get("Transaction") or row.get("Text"),
                "shares": shares,
                "value": value,
                "transaction_price_per_share": price_per_share,
                "transaction_date": str(row.get("Start Date")) if row.get("Start Date") else None,
                "ownership_type": row.get("Ownership"),  # Direct/Indirect
                "filing_url": row.get("URL"),
            })
        return trades
    except Exception:
        return []


# ============================================================================
# 뉴스 데이터
# ============================================================================

def _fetch_company_news_yf(ticker: str, limit: int = 50) -> list:
    """
    Yahoo Finance에서 뉴스 데이터 가져오기

    주요 기능:
    - 최대 50건의 뉴스 조회
    - summary 필드 포함 (content.summary에서 추출)
    - content_type, thumbnail_url 필드 포함
    - Rate limiting 재시도 로직 적용
    """
    try:
        news = safe_get_ticker_news(ticker)

        if not news:
            return []

        news_list = []
        for item in news[:limit]:
            # 새로운 Yahoo Finance 뉴스 구조 지원
            content = item.get("content", {})

            # 제목 추출 (새 구조 우선)
            title = content.get("title") or item.get("title", "")

            # 소스/발행자 추출
            publisher = ""
            if content.get("provider"):
                publisher = content["provider"].get("displayName", "")
            if not publisher:
                publisher = item.get("publisher", "")

            # URL 추출
            url = ""
            if content.get("canonicalUrl"):
                url = content["canonicalUrl"].get("url", "")
            if not url:
                url = item.get("link", "")

            # 날짜 추출
            pub_date = content.get("pubDate")
            if not pub_date and item.get("providerPublishTime"):
                try:
                    pub_date = datetime.fromtimestamp(item["providerPublishTime"]).strftime("%Y-%m-%d %H:%M:%S")
                except (TypeError, ValueError):
                    pub_date = None

            # 썸네일 URL 추출
            thumbnail_url = None
            if content.get("thumbnail"):
                thumbnail_url = content["thumbnail"].get("originalUrl")

            news_list.append({
                "title": title,
                "publisher": publisher,
                "link": url,
                "date": pub_date,
                "summary": content.get("summary", ""),
                "content_type": content.get("contentType"),
                "thumbnail_url": thumbnail_url,
            })
        return news_list
    except Exception:
        return []


# ============================================================================
# 캐시된 데이터 조회 (내부자 거래, 뉴스)
# ============================================================================

def get_insider_trades(ticker: str, end_date: str, limit: int = 100) -> list:
    """캐시된 내부자 거래 데이터 조회"""
    if is_korean_ticker(ticker):
        from korean_data_fetcher import get_insider_trades_kr
        return get_insider_trades_kr(normalize_korean_ticker(ticker), end_date, limit)

    cache_path = _get_cache_path("insider_yf_v2", ticker, end_date, "")
    cached = _read_cache(cache_path)
    if cached is not None:
        cache_stats["hits"] += 1
        return cached

    cache_stats["misses"] += 1
    result = _fetch_insider_trades_yf(ticker, limit)
    if result:
        _write_cache(cache_path, result)
    return result


def get_company_news(ticker: str, end_date: str, limit: int = 50) -> list:
    """캐시된 뉴스 데이터 조회"""
    if is_korean_ticker(ticker):
        from korean_data_fetcher import get_company_news_kr
        return get_company_news_kr(normalize_korean_ticker(ticker), end_date, limit)

    cache_path = _get_cache_path("news_yf_v2", ticker, end_date, "")
    cached = _read_cache(cache_path)
    if cached is not None:
        cache_stats["hits"] += 1
        return cached

    cache_stats["misses"] += 1
    result = _fetch_company_news_yf(ticker, limit)
    if result:
        _write_cache(cache_path, result)
    return result


# ============================================================================
# 재무 지표 (파생 지표 포함)
# ============================================================================

def _calculate_derived_metrics(ticker: str, info: dict) -> dict:
    """
    재무제표 기반 파생 지표 계산

    ROIC, Interest Coverage, Cash Ratio 등 Yahoo Finance info에서
    직접 제공하지 않는 지표들을 재무제표에서 계산합니다.
    """
    derived = {
        "return_on_invested_capital": None,
        "interest_coverage": None,
        "cash_ratio": None,
        "operating_cash_flow_ratio": None,
        "asset_turnover": None,
        "research_and_development": None,
        "research_and_development_ratio": None,
    }

    try:
        income_stmt = safe_get_financials(ticker)
        balance_sheet = safe_get_balance_sheet(ticker)

        if income_stmt is None or (hasattr(income_stmt, 'empty') and income_stmt.empty):
            return derived
        if balance_sheet is None or (hasattr(balance_sheet, 'empty') and balance_sheet.empty):
            return derived

        # 최신 기간의 데이터 사용
        latest_col = income_stmt.columns[0] if len(income_stmt.columns) > 0 else None
        if latest_col is None:
            return derived

        # ROIC = NOPAT / Invested Capital
        try:
            ebit = None
            for ebit_name in ["EBIT", "Operating Income"]:
                if ebit_name in income_stmt.index:
                    val = income_stmt.loc[ebit_name, latest_col]
                    if pd.notna(val):
                        ebit = float(val)
                        break

            if ebit:
                tax_rate = 0.21  # 미국 법인세율 가정 (한국 종목은 korean_data_fetcher로 라우팅되어 여기 도달하지 않음)
                nopat = ebit * (1 - tax_rate)

                total_equity = None
                for eq_name in ["Stockholders Equity", "Total Stockholder Equity", "Total Equity Gross Minority Interest"]:
                    if eq_name in balance_sheet.index:
                        val = balance_sheet.loc[eq_name, latest_col] if latest_col in balance_sheet.columns else None
                        if val is not None and pd.notna(val):
                            total_equity = float(val)
                            break

                total_debt = info.get("totalDebt", 0) or 0
                cash = info.get("totalCash", 0) or 0

                if total_equity:
                    invested_capital = total_equity + total_debt - cash
                    if invested_capital > 0:
                        derived["return_on_invested_capital"] = nopat / invested_capital
        except Exception:
            pass

        # Interest Coverage = EBIT / Interest Expense
        try:
            ebit = None
            for ebit_name in ["EBIT", "Operating Income"]:
                if ebit_name in income_stmt.index:
                    val = income_stmt.loc[ebit_name, latest_col]
                    if pd.notna(val):
                        ebit = float(val)
                        break

            interest_expense = None
            for int_name in ["Interest Expense", "Interest Expense Non Operating"]:
                if int_name in income_stmt.index:
                    val = income_stmt.loc[int_name, latest_col]
                    if pd.notna(val):
                        interest_expense = abs(float(val))
                        break

            if ebit and interest_expense and interest_expense > 0:
                derived["interest_coverage"] = ebit / interest_expense
        except Exception:
            pass

        # Cash Ratio = Cash / Current Liabilities
        try:
            cash = info.get("totalCash", 0) or 0
            current_liabilities = None
            for cl_name in ["Current Liabilities", "Total Current Liabilities"]:
                if cl_name in balance_sheet.index:
                    val = balance_sheet.loc[cl_name, latest_col] if latest_col in balance_sheet.columns else None
                    if val is not None and pd.notna(val):
                        current_liabilities = float(val)
                        break

            if cash and current_liabilities and current_liabilities > 0:
                derived["cash_ratio"] = cash / current_liabilities
        except Exception:
            pass

        # Operating Cash Flow Ratio = Operating Cash Flow / Current Liabilities
        try:
            op_cf = info.get("operatingCashflow", 0) or 0
            if op_cf and current_liabilities and current_liabilities > 0:
                derived["operating_cash_flow_ratio"] = op_cf / current_liabilities
        except Exception:
            pass

        # Asset Turnover = Revenue / Total Assets
        try:
            revenue = info.get("totalRevenue", 0) or 0
            total_assets = None
            if "Total Assets" in balance_sheet.index:
                val = balance_sheet.loc["Total Assets", latest_col] if latest_col in balance_sheet.columns else None
                if val is not None and pd.notna(val):
                    total_assets = float(val)

            if revenue and total_assets and total_assets > 0:
                derived["asset_turnover"] = revenue / total_assets
        except Exception:
            pass

        # R&D (Research and Development) - Fisher 분석용
        try:
            rd_value = None
            for rd_name in ["Research And Development", "Research Development", "Research And Development Expenses"]:
                if rd_name in income_stmt.index:
                    val = income_stmt.loc[rd_name, latest_col]
                    if pd.notna(val):
                        rd_value = float(val)
                        break

            if rd_value and rd_value > 0:
                derived["research_and_development"] = rd_value
                total_rev = info.get("totalRevenue")
                if total_rev and total_rev > 0:
                    derived["research_and_development_ratio"] = rd_value / total_rev
        except Exception:
            pass

    except Exception:
        pass

    return derived


def _fetch_financial_metrics_yf(ticker: str) -> dict:
    """
    Yahoo Finance에서 재무 지표 가져오기

    주요 기능:
    - 기본 + 확장 재무 지표 (enterprise_value, eps, book_value_per_share 등)
    - ROIC, Interest Coverage, Cash Ratio 등 파생 지표 계산
    - 소유권/공매도 지표 포함
    - 기술적 지표 포함 (52주 고/저, 이동평균 등)
    """
    try:
        info = safe_get_ticker_info(ticker)

        if not info:
            return None

        # 파생 지표 계산 (ROIC, Interest Coverage 등)
        derived = _calculate_derived_metrics(ticker, info)

        # 시가총액과 FCF 미리 추출
        market_cap = info.get("marketCap")
        free_cash_flow = info.get("freeCashflow")
        shares_outstanding = info.get("sharesOutstanding")
        total_debt = info.get("totalDebt")

        return {
            "ticker": ticker,

            # ===== 밸류에이션 지표 =====
            "price_to_earnings_ratio": info.get("trailingPE") or info.get("forwardPE"),
            "price_to_book_ratio": info.get("priceToBook"),
            "price_to_sales_ratio": info.get("priceToSalesTrailing12Months"),
            "peg_ratio": info.get("pegRatio"),
            "enterprise_value_to_ebitda": info.get("enterpriseToEbitda"),
            "enterprise_value": info.get("enterpriseValue"),
            "enterprise_value_to_revenue": info.get("enterpriseToRevenue"),

            # ===== 수익성 지표 =====
            "return_on_equity": info.get("returnOnEquity"),
            "return_on_assets": info.get("returnOnAssets"),
            "return_on_invested_capital": derived.get("return_on_invested_capital"),
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "net_margin": info.get("profitMargins"),
            "ebitda": info.get("ebitda"),
            "ebitda_margins": info.get("ebitdaMargins"),

            # ===== 성장 지표 =====
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "earnings_per_share_growth": info.get("earningsQuarterlyGrowth"),

            # ===== 재무 건전성 =====
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
            "debt_to_equity": info.get("debtToEquity") / 100 if info.get("debtToEquity") else None,
            "interest_coverage": derived.get("interest_coverage"),
            "cash_ratio": derived.get("cash_ratio"),
            "operating_cash_flow_ratio": derived.get("operating_cash_flow_ratio"),
            "asset_turnover": derived.get("asset_turnover"),
            "debt_to_assets": (total_debt / (total_debt + market_cap)) if total_debt and market_cap else None,

            # ===== 배당 =====
            "dividend_yield": info.get("dividendYield"),
            "payout_ratio": info.get("payoutRatio"),

            # ===== 시가총액 및 주식 정보 =====
            "market_cap": market_cap,
            "shares_outstanding": shares_outstanding,
            "float_shares": info.get("floatShares"),

            # ===== 현금흐름 =====
            "free_cash_flow": free_cash_flow,
            "free_cash_flow_yield": (free_cash_flow / market_cap) if free_cash_flow and market_cap else None,
            "free_cash_flow_per_share": (free_cash_flow / shares_outstanding) if free_cash_flow and shares_outstanding else None,
            "operating_cashflow": info.get("operatingCashflow"),

            # ===== 부채/현금 =====
            "total_debt": total_debt,
            "total_cash": info.get("totalCash"),
            "total_cash_per_share": info.get("totalCashPerShare"),

            # ===== 매출/수익 =====
            "total_revenue": info.get("totalRevenue"),
            "revenue_per_share": info.get("revenuePerShare"),
            "earnings_per_share": info.get("trailingEps"),
            "forward_eps": info.get("forwardEps"),
            "book_value_per_share": info.get("bookValue"),

            # ===== 소유권/공매도 지표 =====
            "held_percent_insiders": info.get("heldPercentInsiders"),
            "held_percent_institutions": info.get("heldPercentInstitutions"),
            "short_ratio": info.get("shortRatio"),
            "short_percent_of_float": info.get("shortPercentOfFloat"),

            # ===== 기술적 지표 =====
            "beta": info.get("beta"),
            "52_week_high": info.get("fiftyTwoWeekHigh"),
            "52_week_low": info.get("fiftyTwoWeekLow"),
            "52_week_change": info.get("52WeekChange"),
            "50_day_average": info.get("fiftyDayAverage"),
            "200_day_average": info.get("twoHundredDayAverage"),

            # ===== 섹터/인더스트리 정보 =====
            "sector": info.get("sector"),
            "industry": info.get("industry"),

            # ===== R&D 지표 (Fisher 분석용) =====
            "research_and_development": derived.get("research_and_development"),
            "research_and_development_ratio": derived.get("research_and_development_ratio"),
        }
    except Exception:
        return None


# ============================================================================
# 가격 데이터
# ============================================================================

def _fetch_prices_yf(ticker: str, start_date: str, end_date: str) -> list:
    """Yahoo Finance에서 가격 데이터 가져오기 (단일 티커)"""
    try:
        df = safe_get_ticker_history(ticker, start_date, end_date)

        if df is None or df.empty:
            return []

        prices = []
        for date, row in df.iterrows():
            prices.append({
                "time": date.strftime("%Y-%m-%d"),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })
        return prices
    except Exception:
        return []


def batch_fetch_prices(tickers: list, start_date: str, end_date: str) -> dict:
    """
    여러 종목의 가격 데이터를 한 번에 가져오기 (배치 처리)

    한국 티커와 해외 티커를 자동으로 분리하여 각각의 데이터소스로 라우팅합니다.
    - 해외: yf.download() (멀티 티커 배치)
    - 한국: PyKRX (순차 호출)

    Returns:
        dict: {ticker: [price_list]} 형태의 딕셔너리
    """
    if not tickers:
        return {}

    # 한국/해외 티커 분리
    kr_tickers = [t for t in tickers if is_korean_ticker(t)]
    us_tickers = [t for t in tickers if not is_korean_ticker(t)]

    result = {}

    # 한국 티커 처리
    if kr_tickers:
        from korean_data_fetcher import batch_fetch_prices_kr
        kr_normalized = [normalize_korean_ticker(t) for t in kr_tickers]
        kr_result = batch_fetch_prices_kr(kr_normalized, start_date, end_date)
        # 원래 티커명으로 매핑 (정규화 전 이름 유지)
        for orig, norm in zip(kr_tickers, kr_normalized):
            if norm in kr_result:
                result[orig] = kr_result[norm]

    # 해외 티커가 없으면 한국 결과만 반환
    if not us_tickers:
        return result

    try:
        print(f"📊 가격 데이터 배치 다운로드 중... ({len(us_tickers)}개 해외 종목)")

        df = safe_batch_download(
            tickers=us_tickers,
            start=start_date,
            end=end_date,
            group_by='ticker',
        )

        if df is None or df.empty:
            print("   ⚠️  가격 데이터를 가져오지 못했습니다.")
            return result

        # 단일 티커인 경우 컬럼 구조가 다름
        if len(us_tickers) == 1:
            ticker = us_tickers[0]
            prices = []
            for date, row in df.iterrows():
                try:
                    prices.append({
                        "time": date.strftime("%Y-%m-%d"),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": int(row["Volume"]),
                    })
                except (KeyError, ValueError, TypeError):
                    continue
            if prices:
                result[ticker] = prices
        else:
            # 멀티 티커: group_by='ticker'로 인해 (ticker, column) 형태의 멀티인덱스
            for ticker in us_tickers:
                try:
                    if ticker not in df.columns.get_level_values(0):
                        continue

                    ticker_df = df[ticker]
                    if ticker_df.empty or ticker_df['Close'].isna().all():
                        continue

                    prices = []
                    for date, row in ticker_df.iterrows():
                        try:
                            if pd.isna(row["Close"]):
                                continue
                            prices.append({
                                "time": date.strftime("%Y-%m-%d"),
                                "open": float(row["Open"]) if not pd.isna(row["Open"]) else 0,
                                "high": float(row["High"]) if not pd.isna(row["High"]) else 0,
                                "low": float(row["Low"]) if not pd.isna(row["Low"]) else 0,
                                "close": float(row["Close"]),
                                "volume": int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
                            })
                        except (KeyError, ValueError, TypeError):
                            continue

                    if prices:
                        result[ticker] = prices
                except Exception:
                    continue

        print(f"   ✅ {len(result)}개 종목 가격 데이터 로드 완료")
        return result

    except Exception as e:
        print(f"   ⚠️  배치 가격 데이터 조회 실패: {e}")
        return {}


# ============================================================================
# 캐시된 데이터 조회 (재무 지표, 가격)
# ============================================================================

def get_financial_metrics(ticker, end_date, period="ttm", limit=10):
    """캐시된 financial metrics 조회 (Yahoo Finance / 한국 DART+PyKRX)"""
    if is_korean_ticker(ticker):
        from korean_data_fetcher import get_financial_metrics_kr
        kr_ticker = normalize_korean_ticker(ticker)
        cache_path = _get_cache_path("metrics_kr", kr_ticker, end_date, "")
        cached = _read_cache(cache_path)
        if cached is not None:
            cache_stats["hits"] += 1
            return [cached]
        cache_stats["misses"] += 1
        result = get_financial_metrics_kr(kr_ticker, end_date)
        if result:
            _write_cache(cache_path, result)
            return [result]
        return []

    cache_path = _get_cache_path("metrics_yf", ticker, end_date, "")
    cached = _read_cache(cache_path)
    if cached is not None:
        cache_stats["hits"] += 1
        return [cached]

    cache_stats["misses"] += 1
    result = _fetch_financial_metrics_yf(ticker)
    if result:
        _write_cache(cache_path, result)
        return [result]
    return []


def get_prices(ticker, start_date, end_date):
    """캐시된 가격 데이터 조회 (Yahoo Finance / 한국 PyKRX)"""
    if is_korean_ticker(ticker):
        from korean_data_fetcher import get_prices_kr
        kr_ticker = normalize_korean_ticker(ticker)
        cache_path = _get_cache_path("prices_kr", kr_ticker, end_date, start_date)
        cached = _read_cache(cache_path)
        if cached is not None:
            cache_stats["hits"] += 1
            return cached
        cache_stats["misses"] += 1
        result = get_prices_kr(kr_ticker, start_date, end_date)
        if result:
            _write_cache(cache_path, result)
        return result

    cache_path = _get_cache_path("prices_yf", ticker, end_date, start_date)
    cached = _read_cache(cache_path)
    if cached is not None:
        cache_stats["hits"] += 1
        return cached

    cache_stats["misses"] += 1
    result = _fetch_prices_yf(ticker, start_date, end_date)
    if result:
        _write_cache(cache_path, result)
    return result


# ============================================================================
# Wikipedia에서 인덱스 구성종목 동적 조회
# ============================================================================

def fetch_sp500_tickers_from_wikipedia():
    """Wikipedia에서 S&P 500 구성종목 가져오기"""
    try:
        import requests
        import re

        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; StockAnalyzer/1.0)"}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        html = response.text

        pattern = r'<td[^>]*>\s*<a[^>]*href="/wiki/[^"]*"[^>]*title="[^"]*"[^>]*>([A-Z]{1,5})</a>'
        matches = re.findall(pattern, html)

        if len(matches) >= 400:
            seen = set()
            tickers = []
            for t in matches:
                if t not in seen and len(t) <= 5:
                    seen.add(t)
                    tickers.append(t.replace('.', '-'))
            return tickers[:505]

        return None
    except Exception as e:
        print(f"⚠️  Wikipedia에서 S&P 500 목록 조회 실패: {e}")
        return None


def fetch_nasdaq100_tickers_from_wikipedia():
    """Wikipedia에서 NASDAQ-100 구성종목 가져오기"""
    try:
        import requests
        import re

        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; StockAnalyzer/1.0)"}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        html = response.text

        pattern = r'<td[^>]*>\s*<a[^>]*href="/wiki/[^"]*"[^>]*>([A-Z]{1,5})</a>'
        matches = re.findall(pattern, html)

        if len(matches) >= 80:
            seen = set()
            tickers = []
            for t in matches:
                if t not in seen and len(t) <= 5 and t.isupper():
                    seen.add(t)
                    tickers.append(t)
            if len(tickers) >= 90:
                return tickers[:105]

        return None
    except Exception as e:
        print(f"⚠️  Wikipedia에서 NASDAQ-100 목록 조회 실패: {e}")
        return None


def get_index_tickers(index_name: str, use_cache: bool = True) -> list:
    """
    인덱스 구성종목 티커 목록 가져오기

    Args:
        index_name: 'sp500', 'nasdaq100', 'kospi', 'kosdaq', 'kospi200', 'kosdaq150'
        use_cache: 티커 목록 캐시 사용 여부

    Returns:
        티커 목록 (리스트). 한국 인덱스는 PyKRX, 미국 인덱스는 Wikipedia에서 조회.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    cache_path = os.path.join(CACHE_DIR, f"tickers_{index_name}_{today}.json")

    if use_cache and CACHE_ENABLED and os.path.exists(cache_path):
        try:
            with open(cache_path, 'r') as f:
                cached = json.load(f)
                print(f"📋 {index_name.upper()} 티커 목록: 캐시에서 로드 ({len(cached)}개)")
                return cached
        except Exception:
            pass

    # 한국 인덱스 지원 (kospi, kosdaq, krx)
    if is_korean_index(index_name):
        from korean_data_fetcher import get_index_tickers_kr

        # krx: KOSPI + KOSDAQ 전체 합산
        if index_name.lower() == "krx":
            print(f"📋 KRX (KOSPI + KOSDAQ) 전체 구성종목을 PyKRX에서 조회 중...")
            kospi_tickers = get_index_tickers_kr("kospi") or []
            kosdaq_tickers = get_index_tickers_kr("kosdaq") or []
            # 중복 제거 (순서 유지)
            seen = set()
            kr_tickers = []
            for t in kospi_tickers + kosdaq_tickers:
                if t not in seen:
                    seen.add(t)
                    kr_tickers.append(t)
            if kr_tickers:
                print(f"   ✅ KOSPI {len(kospi_tickers)}개 + KOSDAQ {len(kosdaq_tickers)}개 = 총 {len(kr_tickers)}개 종목 조회 완료")
        else:
            print(f"📋 {index_name.upper()} 구성종목을 PyKRX에서 조회 중...")
            kr_tickers = get_index_tickers_kr(index_name)

        if kr_tickers:
            if index_name.lower() != "krx":
                print(f"   ✅ PyKRX에서 {len(kr_tickers)}개 종목 조회 완료")
            if use_cache and CACHE_ENABLED:
                try:
                    if not os.path.exists(CACHE_DIR):
                        os.makedirs(CACHE_DIR)
                    with open(cache_path, 'w') as f:
                        json.dump(kr_tickers, f)
                except Exception:
                    pass
        else:
            print(f"   ⚠️ {index_name.upper()} 종목 조회 실패")
            kr_tickers = []
        return kr_tickers

    tickers = None
    if index_name == "sp500":
        print("📋 S&P 500 구성종목을 Wikipedia에서 조회 중...")
        tickers = fetch_sp500_tickers_from_wikipedia()
        fallback = FALLBACK_SP500
    elif index_name == "nasdaq100":
        print("📋 NASDAQ-100 구성종목을 Wikipedia에서 조회 중...")
        tickers = fetch_nasdaq100_tickers_from_wikipedia()
        fallback = FALLBACK_NASDAQ100
    else:
        raise ValueError(f"알 수 없는 인덱스: {index_name}")

    if tickers is None:
        tickers = [t.strip() for t in fallback.split(',')]
        print(f"   폴백 목록 사용: {len(tickers)}개 종목")
    else:
        print(f"   ✅ Wikipedia에서 {len(tickers)}개 종목 조회 완료")
        if use_cache and CACHE_ENABLED:
            try:
                if not os.path.exists(CACHE_DIR):
                    os.makedirs(CACHE_DIR)
                with open(cache_path, 'w') as f:
                    json.dump(tickers, f)
            except Exception:
                pass

    return tickers


def sort_tickers_by_market_cap(tickers, top_n=0):
    """티커를 시가총액 기준으로 정렬 (한국/해외 자동 분기)"""
    print(f"📊 {len(tickers)}개 종목을 시가총액 기준으로 정렬 중...")

    market_caps = {}
    batch_size = 50

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        for ticker in batch:
            try:
                if is_korean_ticker(ticker):
                    from korean_data_fetcher import get_market_cap_kr
                    kr_ticker = normalize_korean_ticker(ticker)
                    cap = get_market_cap_kr(kr_ticker, datetime.now().strftime("%Y-%m-%d"))
                    market_caps[ticker] = cap or 0
                else:
                    info = safe_get_ticker_info(ticker)
                    market_cap = info.get("marketCap", 0) or 0 if info else 0
                    market_caps[ticker] = market_cap
            except Exception:
                market_caps[ticker] = 0

    sorted_tickers = sorted(tickers, key=lambda t: market_caps.get(t, 0), reverse=True)

    if top_n > 0:
        sorted_tickers = sorted_tickers[:top_n]

    print(f"   시가총액 상위 10개: {sorted_tickers[:10]}")
    return sorted_tickers
