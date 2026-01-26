#!/usr/bin/env python3
"""
Stock Analyzer - End-to-End 종목 분석 및 순위 산정 (Yahoo Finance 버전)

사용법:
    # 특정 종목 분석
    python analyze_stocks.py --tickers AAPL,GOOGL,MSFT,NVDA,TSLA

    # S&P 500 전체 분석 (상위 N개 출력)
    python analyze_stocks.py --index sp500 --top 30

    # 결과를 파일로 저장
    python analyze_stocks.py --index sp500 --output results.json

    # 캐시 없이 실행
    python analyze_stocks.py --index sp500 --no-cache

    # 캐시 삭제
    python analyze_stocks.py --clear-cache

    # Wikipedia에서 최신 티커 목록 갱신
    python analyze_stocks.py --index sp500 --update-tickers
"""
import os
import sys
import json
import argparse
import hashlib
import shutil
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

try:
    import yfinance as yf
except ImportError:
    print("yfinance가 설치되지 않았습니다.")
    print("설치: pip install yfinance")
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    print("pandas가 설치되지 않았습니다.")
    print("설치: pip install pandas")
    sys.exit(1)

# ============================================================================
# 파일 기반 캐시
# ============================================================================

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
CACHE_ENABLED = True  # 글로벌 캐시 활성화 플래그

# 캐시 히트/미스 카운터
cache_stats = {"hits": 0, "misses": 0}


def _ensure_cache_dir():
    """캐시 디렉토리 생성"""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)


def _get_cache_path(cache_type: str, ticker: str, date: str, extra: str = "") -> str:
    """캐시 파일 경로 생성"""
    key = f"{cache_type}_{ticker}_{date}_{extra}"
    filename = hashlib.md5(key.encode()).hexdigest()[:16] + ".json"
    return os.path.join(CACHE_DIR, date, filename)


def _read_cache(cache_path: str):
    """캐시 파일 읽기"""
    if not CACHE_ENABLED:
        return None
    try:
        if os.path.exists(cache_path):
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _write_cache(cache_path: str, data):
    """캐시 파일 쓰기"""
    if not CACHE_ENABLED:
        return
    try:
        cache_dir = os.path.dirname(cache_path)
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def clear_cache():
    """캐시 디렉토리 삭제"""
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
        print(f"캐시 삭제 완료: {CACHE_DIR}")
    else:
        print("삭제할 캐시가 없습니다.")


def get_cache_stats():
    """캐시 통계 반환"""
    if not os.path.exists(CACHE_DIR):
        return {"total_files": 0, "total_size_mb": 0, "dates": []}

    total_files = 0
    total_size = 0
    dates = []

    for date_dir in os.listdir(CACHE_DIR):
        date_path = os.path.join(CACHE_DIR, date_dir)
        if os.path.isdir(date_path):
            dates.append(date_dir)
            for f in os.listdir(date_path):
                total_files += 1
                total_size += os.path.getsize(os.path.join(date_path, f))

    return {
        "total_files": total_files,
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "dates": sorted(dates, reverse=True)
    }


# ============================================================================
# Yahoo Finance 데이터 조회 함수 (캐시 포함)
# ============================================================================

def _fetch_insider_trades_yf(ticker: str, limit: int = 100) -> list:
    """
    Yahoo Finance에서 내부자 거래 데이터 가져오기 (개선된 버전)

    개선 사항:
    - limit 50 → 100으로 증가
    - transaction_price_per_share 계산 추가
    - transaction_date, ownership_type, filing_url 필드 추가
    """
    try:
        stock = yf.Ticker(ticker)
        insider_df = stock.insider_transactions

        if insider_df is None or insider_df.empty:
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
                # 새로 추가된 필드
                "transaction_price_per_share": price_per_share,
                "transaction_date": str(row.get("Start Date")) if row.get("Start Date") else None,
                "ownership_type": row.get("Ownership"),  # Direct/Indirect
                "filing_url": row.get("URL"),
            })
        return trades
    except Exception:
        return []


def _fetch_company_news_yf(ticker: str, limit: int = 50) -> list:
    """
    Yahoo Finance에서 뉴스 데이터 가져오기 (개선된 버전)

    개선 사항:
    - limit 20 → 50으로 증가
    - summary 필드 추가 (content.summary에서 추출)
    - content_type, thumbnail_url 필드 추가
    """
    try:
        stock = yf.Ticker(ticker)
        news = stock.news

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
                # 새로 추가된 필드
                "summary": content.get("summary", ""),
                "content_type": content.get("contentType"),
                "thumbnail_url": thumbnail_url,
            })
        return news_list
    except Exception:
        return []


def get_insider_trades(ticker: str, end_date: str, limit: int = 100) -> list:
    """캐시된 내부자 거래 데이터 조회 (limit 50 → 100으로 증가)"""
    cache_path = _get_cache_path("insider_yf_v2", ticker, end_date, "")  # 캐시 키 변경 (새 필드 포함)
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
    """캐시된 뉴스 데이터 조회 (limit 20 → 50으로 증가, summary 포함)"""
    cache_path = _get_cache_path("news_yf_v2", ticker, end_date, "")  # 캐시 키 변경 (새 필드 포함)
    cached = _read_cache(cache_path)
    if cached is not None:
        cache_stats["hits"] += 1
        return cached

    cache_stats["misses"] += 1
    result = _fetch_company_news_yf(ticker, limit)
    if result:
        _write_cache(cache_path, result)
    return result


def _calculate_derived_metrics(stock, info: dict) -> dict:
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
    }

    try:
        income_stmt = stock.financials
        balance_sheet = stock.balance_sheet

        if income_stmt is None or income_stmt.empty:
            return derived
        if balance_sheet is None or balance_sheet.empty:
            return derived

        # 최신 기간의 데이터 사용
        latest_col = income_stmt.columns[0] if len(income_stmt.columns) > 0 else None
        if latest_col is None:
            return derived

        # ROIC = NOPAT / Invested Capital
        # NOPAT = Operating Income * (1 - Tax Rate)
        # Invested Capital = Total Equity + Total Debt - Cash
        try:
            ebit = None
            for ebit_name in ["EBIT", "Operating Income"]:
                if ebit_name in income_stmt.index:
                    val = income_stmt.loc[ebit_name, latest_col]
                    if pd.notna(val):
                        ebit = float(val)
                        break

            if ebit:
                tax_rate = 0.21  # 미국 법인세율 가정
                nopat = ebit * (1 - tax_rate)

                # Invested Capital 계산
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

    except Exception:
        pass

    return derived


def _fetch_financial_metrics_yf(ticker: str) -> dict:
    """
    Yahoo Finance에서 재무 지표 가져오기 (개선된 버전)

    개선 사항:
    - 15개 이상의 추가 필드 (enterprise_value, eps, book_value_per_share 등)
    - ROIC, Interest Coverage, Cash Ratio 등 파생 지표 계산
    - 소유권/공매도 지표 추가
    - 기술적 지표 추가 (52주 고/저, 이동평균 등)
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        # 파생 지표 계산 (ROIC, Interest Coverage 등)
        derived = _calculate_derived_metrics(stock, info)

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
            # 새로 추가
            "enterprise_value": info.get("enterpriseValue"),
            "enterprise_value_to_revenue": info.get("enterpriseToRevenue"),

            # ===== 수익성 지표 =====
            "return_on_equity": info.get("returnOnEquity"),
            "return_on_assets": info.get("returnOnAssets"),
            "return_on_invested_capital": derived.get("return_on_invested_capital"),  # 계산된 ROIC
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "net_margin": info.get("profitMargins"),
            # 새로 추가
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
            # 새로 추가
            "interest_coverage": derived.get("interest_coverage"),  # 계산된 이자보상배율
            "cash_ratio": derived.get("cash_ratio"),  # 계산된 현금비율
            "operating_cash_flow_ratio": derived.get("operating_cash_flow_ratio"),  # 계산된 영업CF비율
            "asset_turnover": derived.get("asset_turnover"),  # 계산된 자산회전율
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

            # ===== 소유권/공매도 지표 (새로 추가) =====
            "held_percent_insiders": info.get("heldPercentInsiders"),
            "held_percent_institutions": info.get("heldPercentInstitutions"),
            "short_ratio": info.get("shortRatio"),
            "short_percent_of_float": info.get("shortPercentOfFloat"),

            # ===== 기술적 지표 (새로 추가) =====
            "beta": info.get("beta"),
            "52_week_high": info.get("fiftyTwoWeekHigh"),
            "52_week_low": info.get("fiftyTwoWeekLow"),
            "52_week_change": info.get("52WeekChange"),
            "50_day_average": info.get("fiftyDayAverage"),
            "200_day_average": info.get("twoHundredDayAverage"),
        }
    except Exception as e:
        return None


def _fetch_prices_yf(ticker: str, start_date: str, end_date: str) -> list:
    """Yahoo Finance에서 가격 데이터 가져오기 (단일 티커)"""
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(start=start_date, end=end_date)

        if df.empty:
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
    except Exception as e:
        return []


def batch_fetch_prices(tickers: list, start_date: str, end_date: str) -> dict:
    """
    Yahoo Finance에서 여러 종목의 가격 데이터를 한 번에 가져오기 (배치 처리)

    yf.download()는 멀티 티커를 지원하며 내부적으로 스레딩을 사용하여
    개별 호출 대비 훨씬 효율적입니다.

    Returns:
        dict: {ticker: [price_list]} 형태의 딕셔너리
    """
    if not tickers:
        return {}

    try:
        print(f"📊 가격 데이터 배치 다운로드 중... ({len(tickers)}개 종목)")

        # yf.download()로 모든 티커의 가격을 한 번에 가져옴
        # threads=True: 자동 병렬 처리
        # group_by='ticker': 티커별로 그룹화
        df = yf.download(
            tickers=tickers,
            start=start_date,
            end=end_date,
            threads=True,
            group_by='ticker',
            progress=False,  # 진행 표시 비활성화 (자체 진행률 사용)
        )

        if df.empty:
            print("   ⚠️  가격 데이터를 가져오지 못했습니다.")
            return {}

        result = {}

        # 단일 티커인 경우 컬럼 구조가 다름
        if len(tickers) == 1:
            ticker = tickers[0]
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
            for ticker in tickers:
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


def get_financial_metrics(ticker, end_date, period="ttm", limit=10):
    """캐시된 financial metrics 조회 (Yahoo Finance)"""
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
    """캐시된 가격 데이터 조회 (Yahoo Finance)"""
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
# 인덱스 종목 리스트 (폴백용 하드코딩)
# ============================================================================

FALLBACK_SP500 = """MMM,AOS,ABT,ABBV,ACN,ADBE,AMD,AES,AFL,A,APD,ABNB,AKAM,ALB,ARE,ALGN,ALLE,LNT,ALL,GOOGL,MO,AMZN,AMCR,AEE,AEP,AXP,AIG,AMT,AWK,AMP,AME,AMGN,APH,ADI,AON,APA,APO,AAPL,AMAT,APTV,ACGL,ADM,ANET,AJG,AIZ,T,ATO,ADSK,ADP,AZO,AVB,AVY,AXON,BKR,BALL,BAC,BAX,BDX,BBY,TECH,BIIB,BLK,BX,BK,BA,BKNG,BSX,BMY,AVGO,BR,BRO,BLDR,BG,BXP,CHRW,CDNS,CZR,CPT,CPB,COF,CAH,KMX,CCL,CARR,CAT,CBOE,CBRE,CDW,COR,CNC,CNP,CF,CRL,SCHW,CHTR,CVX,CMG,CB,CHD,CI,CINF,CTAS,CSCO,C,CFG,CLX,CME,CMS,KO,CTSH,COIN,CL,CMCSA,CAG,COP,ED,STZ,CEG,COO,CPRT,GLW,CPAY,CTVA,CSGP,COST,CTRA,CRWD,CCI,CSX,CMI,CVS,DHR,DRI,DDOG,DVA,DAY,DECK,DE,DELL,DAL,DVN,DXCM,FANG,DLR,DG,DLTR,D,DPZ,DASH,DOV,DOW,DHI,DTE,DUK,DD,EMN,ETN,EBAY,ECL,EIX,EW,EA,ELV,EMR,ENPH,ETR,EOG,EPAM,EQT,EFX,EQIX,EQR,ERIE,ESS,EL,EG,EVRG,ES,EXC,EXE,EXPE,EXPD,EXR,XOM,FFIV,FDS,FICO,FAST,FRT,FDX,FIS,FITB,FSLR,FE,FI,F,FTNT,FTV,FOXA,FOX,BEN,FCX,GRMN,IT,GE,GEHC,GEV,GEN,GNRC,GD,GIS,GM,GPC,GILD,GPN,GL,GDDY,GS,HAL,HIG,HAS,HCA,DOC,HSIC,HSY,HPE,HLT,HOLX,HD,HON,HRL,HST,HWM,HPQ,HUBB,HUM,HBAN,HII,IBM,IEX,IDXX,ITW,INCY,IR,PODD,INTC,ICE,IFF,IP,IPG,INTU,ISRG,IVZ,INVH,IQV,IRM,JBHT,JBL,JKHY,J,JNJ,JCI,JPM,KVUE,KDP,KEY,KEYS,KMB,KIM,KMI,KKR,KLAC,KHC,KR,LHX,LH,LRCX,LW,LVS,LDOS,LEN,LII,LLY,LIN,LYV,LKQ,LMT,L,LOW,LULU,LYB,MTB,MPC,MKTX,MAR,MMC,MLM,MAS,MA,MTCH,MKC,MCD,MCK,MDT,MRK,META,MET,MTD,MGM,MCHP,MU,MSFT,MAA,MRNA,MHK,MOH,TAP,MDLZ,MPWR,MNST,MCO,MS,MOS,MSI,MSCI,NDAQ,NTAP,NFLX,NEM,NWSA,NWS,NEE,NKE,NI,NDSN,NSC,NTRS,NOC,NCLH,NRG,NUE,NVDA,NVR,NXPI,ORLY,OXY,ODFL,OMC,ON,OKE,ORCL,OTIS,PCAR,PKG,PANW,PARA,PH,PAYX,PAYC,PYPL,PNR,PEP,PFE,PCG,PM,PSX,PNW,PNC,POOL,PPG,PPL,PFG,PG,PGR,PLD,PRU,PEG,PTC,PSA,PHM,QRVO,PWR,QCOM,DGX,RL,RJF,RTX,O,REG,REGN,RF,RSG,RMD,RVTY,ROK,ROL,ROP,ROST,RCL,SPGI,CRM,SBAC,SLB,STX,SRE,NOW,SHW,SPG,SWKS,SJM,SW,SNA,SOLV,SO,LUV,SWK,SBUX,STT,STLD,STE,SYK,SMCI,SYF,SNPS,SYY,TMUS,TROW,TTWO,TPR,TRGP,TGT,TEL,TDY,TFX,TER,TSLA,TXN,TXT,TMO,TJX,TSCO,TT,TDG,TRV,TRMB,TFC,TYL,TSN,USB,UBER,UDR,ULTA,UNP,UAL,UPS,URI,UNH,UHS,VLO,VTR,VLTO,VRSN,VRSK,VZ,VRTX,VIAV,V,VST,VMC,WRB,GWW,WAB,WBA,WMT,DIS,WBD,WM,WAT,WEC,WFC,WELL,WST,WDC,WY,WMB,WTW,WYNN,XEL,XYL,YUM,ZBRA,ZBH,ZTS"""

FALLBACK_NASDAQ100 = """AAPL,ABNB,ADBE,ADI,ADP,ADSK,AEP,AMAT,AMGN,AMZN,ANSS,ARM,ASML,AVGO,AZN,BIIB,BKNG,BKR,CDNS,CDW,CEG,CHTR,CMCSA,COST,CPRT,CRWD,CSCO,CSGP,CSX,CTAS,CTSH,DDOG,DLTR,DXCM,EA,EXC,FANG,FAST,FTNT,GEHC,GFS,GILD,GOOG,GOOGL,HON,IDXX,ILMN,INTC,INTU,ISRG,KDP,KHC,KLAC,LIN,LRCX,LULU,MAR,MCHP,MDB,MDLZ,MELI,META,MNST,MRNA,MRVL,MSFT,MU,NFLX,NVDA,NXPI,ODFL,ON,ORLY,PANW,PAYX,PCAR,PDD,PEP,PYPL,QCOM,REGN,ROP,ROST,SBUX,SMCI,SNPS,TEAM,TMUS,TSLA,TTD,TTWO,TXN,VRSK,VRTX,WBD,WDAY,XEL,ZS"""


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

        # HTML에서 티커 추출 (테이블의 첫 번째 컬럼)
        # 패턴: <td>... <a ...>TICKER</a> 또는 <td>TICKER</td>
        html = response.text

        # 테이블에서 Symbol 컬럼 찾기
        # S&P 500 테이블의 티커는 보통 href="/wiki/TICKER" 형식
        pattern = r'<td[^>]*>\s*<a[^>]*href="/wiki/[^"]*"[^>]*title="[^"]*"[^>]*>([A-Z]{1,5})</a>'
        matches = re.findall(pattern, html)

        if len(matches) >= 400:  # S&P 500은 500개 이상이어야 함
            # 중복 제거하면서 순서 유지
            seen = set()
            tickers = []
            for t in matches:
                if t not in seen and len(t) <= 5:
                    seen.add(t)
                    tickers.append(t.replace('.', '-'))
            return tickers[:505]  # 최대 505개 (일부 추가 가능)

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

        # NASDAQ-100 테이블의 티커 추출
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
        index_name: 'sp500' 또는 'nasdaq100'
        use_cache: 티커 목록 캐시 사용 여부

    Returns:
        티커 목록 (리스트)
    """
    # 티커 목록 캐시 (날짜별)
    today = datetime.now().strftime("%Y-%m-%d")
    cache_path = os.path.join(CACHE_DIR, f"tickers_{index_name}_{today}.json")

    # 캐시 확인
    if use_cache and CACHE_ENABLED and os.path.exists(cache_path):
        try:
            with open(cache_path, 'r') as f:
                cached = json.load(f)
                print(f"📋 {index_name.upper()} 티커 목록: 캐시에서 로드 ({len(cached)}개)")
                return cached
        except Exception:
            pass

    # Wikipedia에서 조회
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

    # 폴백 사용
    if tickers is None:
        tickers = [t.strip() for t in fallback.split(',')]
        print(f"   폴백 목록 사용: {len(tickers)}개 종목")
    else:
        print(f"   ✅ Wikipedia에서 {len(tickers)}개 종목 조회 완료")
        # 캐시 저장
        if use_cache and CACHE_ENABLED:
            try:
                if not os.path.exists(CACHE_DIR):
                    os.makedirs(CACHE_DIR)
                with open(cache_path, 'w') as f:
                    json.dump(tickers, f)
            except Exception:
                pass

    return tickers

# ============================================================================
# 설정
# ============================================================================

MAX_WORKERS = 10
DEFAULT_PERIOD = "1Y"

# 팩터별 가중치 (앙상블 분석)
FACTOR_WEIGHTS = {
    "value": 0.25,      # 버핏, 그레이엄, 멍거 스타일
    "growth": 0.20,     # 린치, 캐시우드 스타일
    "quality": 0.20,    # 멍거, 피셔 스타일
    "momentum": 0.10,   # 드러켄밀러 스타일
    "safety": 0.10,     # 파브라이, 버핏 스타일
    "sentiment": 0.08,  # 뉴스 센티먼트
    "insider": 0.07,    # 내부자 거래
}

# ============================================================================
# 시가총액 카테고리
# ============================================================================

def get_market_cap_category(market_cap):
    """시가총액 기반 카테고리 분류"""
    if not market_cap:
        return None, "N/A"

    cap_b = market_cap / 1e9  # 십억 달러 단위

    if cap_b >= 200:
        return "mega", f"${cap_b:.0f}B"
    elif cap_b >= 10:
        return "large", f"${cap_b:.0f}B"
    elif cap_b >= 2:
        return "mid", f"${cap_b:.1f}B"
    else:
        return "small", f"${cap_b*1000:.0f}M"


def calculate_size_bonus(market_cap, growth_score):
    """
    시가총액 기반 보너스 점수 (피터 린치/준준왈라 스타일)
    - 고성장 소형주: 10배 수익 가능성 → 가산점
    - 대형주: 안정성 → 약간의 가산점
    """
    if not market_cap:
        return 0, []

    category, _ = get_market_cap_category(market_cap)
    score = 0
    factors = []

    if category == "small":
        # 소형주 + 고성장 = 피터 린치의 '텐배거' 후보
        if growth_score >= 6:
            score += 2
            factors.append("소형 고성장주 (텐배거 후보)")
        elif growth_score >= 3:
            score += 1
            factors.append("소형 성장주")
    elif category == "mid":
        # 중형주 + 성장 = 균형잡힌 기회
        if growth_score >= 4:
            score += 1
            factors.append("중형 성장주")
    elif category == "mega":
        # 메가캡은 성장 제한적
        score -= 0.5

    return score, factors


# ============================================================================
# 멀티팩터 분석 로직
# ============================================================================

def calculate_value_score(metrics):
    """가치 투자 점수 (버핏/그레이엄/멍거 스타일)"""
    if not metrics:
        return 0, []

    m = metrics[0]
    score = 0
    factors = []

    # P/E 비율
    pe = m.get('price_to_earnings_ratio')
    if pe:
        if 0 < pe < 12:
            score += 4
            factors.append(f"매우 낮은 P/E ({pe:.1f})")
        elif 0 < pe < 18:
            score += 2
            factors.append(f"적정 P/E ({pe:.1f})")
        elif pe > 35:
            score -= 2

    # P/B 비율
    pb = m.get('price_to_book_ratio')
    if pb:
        if 0 < pb < 1.5:
            score += 3
            factors.append(f"저평가 P/B ({pb:.2f})")
        elif 0 < pb < 3:
            score += 1
        elif pb > 8:
            score -= 1

    # EV/EBITDA
    ev_ebitda = m.get('enterprise_value_to_ebitda')
    if ev_ebitda:
        if 0 < ev_ebitda < 8:
            score += 2
            factors.append(f"낮은 EV/EBITDA ({ev_ebitda:.1f})")
        elif 0 < ev_ebitda < 12:
            score += 1

    # FCF Yield
    fcf_yield = m.get('free_cash_flow_yield')
    if fcf_yield:
        if fcf_yield > 0.08:
            score += 3
            factors.append(f"높은 FCF Yield ({fcf_yield*100:.1f}%)")
        elif fcf_yield > 0.05:
            score += 1

    return score, factors


def calculate_growth_score(metrics):
    """성장 투자 점수 (린치/캐시우드 스타일)"""
    if not metrics:
        return 0, []

    m = metrics[0]
    score = 0
    factors = []

    # 매출 성장률
    rev_growth = m.get('revenue_growth')
    if rev_growth:
        if rev_growth > 0.25:
            score += 4
            factors.append(f"고성장 매출 (+{rev_growth*100:.0f}%)")
        elif rev_growth > 0.15:
            score += 2
            factors.append(f"양호한 매출 성장 (+{rev_growth*100:.0f}%)")
        elif rev_growth > 0.08:
            score += 1
        elif rev_growth < 0:
            score -= 2

    # EPS 성장률
    eps_growth = m.get('earnings_per_share_growth')
    if eps_growth:
        if eps_growth > 0.25:
            score += 3
        elif eps_growth > 0.15:
            score += 2
        elif eps_growth > 0.08:
            score += 1

    # PEG 비율 (린치 스타일)
    peg = m.get('peg_ratio')
    if peg:
        if 0 < peg < 0.8:
            score += 4
            factors.append(f"매력적 PEG ({peg:.2f})")
        elif 0 < peg < 1.2:
            score += 2
            factors.append(f"적정 PEG ({peg:.2f})")
        elif peg > 2.5:
            score -= 1

    return score, factors


def calculate_quality_score(metrics):
    """품질 점수 (멍거/피셔 스타일)"""
    if not metrics:
        return 0, []

    m = metrics[0]
    score = 0
    factors = []

    # ROE
    roe = m.get('return_on_equity')
    if roe:
        if roe > 0.25:
            score += 4
            factors.append(f"뛰어난 ROE ({roe*100:.0f}%)")
        elif roe > 0.18:
            score += 2
            factors.append(f"양호한 ROE ({roe*100:.0f}%)")
        elif roe > 0.12:
            score += 1
        elif roe < 0.05:
            score -= 2

    # ROIC
    roic = m.get('return_on_invested_capital')
    if roic:
        if roic > 0.20:
            score += 3
            factors.append(f"높은 ROIC ({roic*100:.0f}%)")
        elif roic > 0.12:
            score += 1

    # 영업이익률
    op_margin = m.get('operating_margin')
    if op_margin:
        if op_margin > 0.25:
            score += 2
            factors.append(f"높은 영업마진 ({op_margin*100:.0f}%)")
        elif op_margin > 0.15:
            score += 1
        elif op_margin < 0.05:
            score -= 1

    # 순이익률
    net_margin = m.get('net_margin')
    if net_margin:
        if net_margin > 0.20:
            score += 2
        elif net_margin > 0.10:
            score += 1

    return score, factors


def calculate_momentum_score(prices):
    """모멘텀 점수 (드러켄밀러 스타일)"""
    if not prices or len(prices) < 60:
        return 0, []

    score = 0
    factors = []

    try:
        current = prices[-1].get('close', 0)
        price_20d = prices[-20].get('close', current) if len(prices) >= 20 else current
        price_60d = prices[-60].get('close', current) if len(prices) >= 60 else current

        # 1개월 모멘텀
        mom_1m = (current - price_20d) / price_20d if price_20d else 0
        if mom_1m > 0.10:
            score += 3
            factors.append(f"강한 1M 모멘텀 (+{mom_1m*100:.0f}%)")
        elif mom_1m > 0.03:
            score += 1
        elif mom_1m < -0.10:
            score -= 2

        # 3개월 모멘텀
        mom_3m = (current - price_60d) / price_60d if price_60d else 0
        if mom_3m > 0.20:
            score += 2
            factors.append(f"강한 3M 모멘텀 (+{mom_3m*100:.0f}%)")
        elif mom_3m > 0.08:
            score += 1
        elif mom_3m < -0.15:
            score -= 2

    except Exception:
        pass

    return score, factors


def calculate_enhanced_momentum_score(prices, lookback_short=20, lookback_long=60):
    """
    강화된 모멘텀 점수 계산 (0-10 스케일)
    - 단기/장기 가격 추세
    - RSI 보정
    - 추세 지속성 보너스
    """
    if not prices or len(prices) < lookback_long:
        return 5.0, {"short_momentum": 0, "long_momentum": 0, "rsi": 50, "trend": "neutral"}

    try:
        closes = [p.get('close', 0) for p in prices]
        if not closes or closes[-1] == 0:
            return 5.0, {"short_momentum": 0, "long_momentum": 0, "rsi": 50, "trend": "neutral"}

        current = closes[-1]

        # 단기 모멘텀 (20일)
        short_price = closes[-lookback_short] if len(closes) >= lookback_short else closes[0]
        short_momentum = (current - short_price) / short_price if short_price > 0 else 0

        # 장기 모멘텀 (60일)
        long_price = closes[-lookback_long] if len(closes) >= lookback_long else closes[0]
        long_momentum = (current - long_price) / long_price if long_price > 0 else 0

        # RSI 계산 (14일)
        rsi = 50
        if len(closes) >= 15:
            gains = []
            losses = []
            for i in range(-14, 0):
                change = closes[i] - closes[i-1]
                if change > 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(abs(change))
            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            else:
                rsi = 100 if avg_gain > 0 else 50

        # 모멘텀 점수 계산 (0-10 스케일)
        # 단기 모멘텀 기여 (최대 4점)
        short_score = 0
        if short_momentum > 0.15:
            short_score = 4
        elif short_momentum > 0.08:
            short_score = 3
        elif short_momentum > 0.03:
            short_score = 2
        elif short_momentum > 0:
            short_score = 1
        elif short_momentum > -0.05:
            short_score = 0.5
        else:
            short_score = 0

        # 장기 모멘텀 기여 (최대 4점)
        long_score = 0
        if long_momentum > 0.25:
            long_score = 4
        elif long_momentum > 0.15:
            long_score = 3
        elif long_momentum > 0.08:
            long_score = 2
        elif long_momentum > 0:
            long_score = 1
        elif long_momentum > -0.10:
            long_score = 0.5
        else:
            long_score = 0

        # RSI 보정 (최대 2점)
        rsi_score = 0
        if 40 <= rsi <= 60:
            rsi_score = 1  # 중립 영역
        elif 30 <= rsi < 40 or 60 < rsi <= 70:
            rsi_score = 1.5  # 적정 영역
        elif rsi < 30:
            rsi_score = 2  # 과매도 (반등 기대)
        elif rsi > 70:
            rsi_score = 0.5  # 과매수 (조정 가능)

        # 추세 지속성 보너스
        trend = "neutral"
        trend_bonus = 0
        if short_momentum > 0 and long_momentum > 0:
            trend = "bullish"
            trend_bonus = 0.5
        elif short_momentum < 0 and long_momentum < 0:
            trend = "bearish"
            trend_bonus = -0.5

        total_score = short_score + long_score + rsi_score + trend_bonus
        total_score = max(0, min(10, total_score))  # 0-10 범위로 제한

        details = {
            "short_momentum": round(short_momentum * 100, 1),
            "long_momentum": round(long_momentum * 100, 1),
            "rsi": round(rsi, 1),
            "trend": trend,
        }

        return round(total_score, 2), details

    except Exception:
        return 5.0, {"short_momentum": 0, "long_momentum": 0, "rsi": 50, "trend": "neutral"}


def sort_tickers_by_market_cap(tickers, top_n=0):
    """티커를 시가총액 기준으로 정렬"""
    print(f"📊 {len(tickers)}개 종목을 시가총액 기준으로 정렬 중...")

    market_caps = {}
    batch_size = 50

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        for ticker in batch:
            try:
                stock = yf.Ticker(ticker)
                info = stock.info
                market_cap = info.get("marketCap", 0) or 0
                market_caps[ticker] = market_cap
            except Exception:
                market_caps[ticker] = 0

    # 시가총액 기준 내림차순 정렬
    sorted_tickers = sorted(tickers, key=lambda t: market_caps.get(t, 0), reverse=True)

    if top_n > 0:
        sorted_tickers = sorted_tickers[:top_n]

    print(f"   시가총액 상위 10개: {sorted_tickers[:10]}")
    return sorted_tickers


def calculate_safety_score(metrics):
    """
    안전성 점수 (파브라이/버핏 스타일) - 개선된 버전

    개선 사항:
    - interest_coverage: 이제 실제로 계산됨 (EBIT / Interest Expense)
    - cash_ratio 추가: 현금 / 유동부채
    - quick_ratio 추가: (유동자산 - 재고) / 유동부채
    - 소유권 안정성 지표 추가: 기관/내부자 보유 비율
    """
    if not metrics:
        return 0, []

    m = metrics[0]
    score = 0
    factors = []

    # 부채비율 (D/E)
    debt_equity = m.get('debt_to_equity')
    if debt_equity is not None:
        if debt_equity < 0.3:
            score += 3
            factors.append("낮은 부채")
        elif debt_equity < 0.7:
            score += 1
        elif debt_equity > 2:
            score -= 2
            factors.append("높은 부채 위험")

    # 유동비율
    current_ratio = m.get('current_ratio')
    if current_ratio:
        if current_ratio > 2.5:
            score += 2
            factors.append(f"양호한 유동비율 ({current_ratio:.1f})")
        elif current_ratio > 1.5:
            score += 1
        elif current_ratio < 1:
            score -= 2
            factors.append("유동성 위험")

    # 당좌비율 (Quick Ratio) - 새로 추가
    quick_ratio = m.get('quick_ratio')
    if quick_ratio:
        if quick_ratio > 1.5:
            score += 1
        elif quick_ratio < 0.5:
            score -= 1

    # 현금비율 (Cash Ratio) - 새로 추가 (계산된 지표)
    cash_ratio = m.get('cash_ratio')
    if cash_ratio:
        if cash_ratio > 0.5:
            score += 2
            factors.append(f"충분한 현금보유 ({cash_ratio:.2f})")
        elif cash_ratio > 0.2:
            score += 1
        elif cash_ratio < 0.1:
            score -= 1

    # 이자보상배율 (Interest Coverage) - 이제 실제로 계산됨
    interest_coverage = m.get('interest_coverage')
    if interest_coverage:
        if interest_coverage > 10:
            score += 2
            factors.append(f"충분한 이자보상 ({interest_coverage:.1f}x)")
        elif interest_coverage > 5:
            score += 1
        elif interest_coverage < 2:
            score -= 2
            factors.append("이자보상 위험")

    # 영업현금흐름 비율 - 새로 추가 (계산된 지표)
    ocf_ratio = m.get('operating_cash_flow_ratio')
    if ocf_ratio:
        if ocf_ratio > 1.0:
            score += 1
            factors.append("강한 영업현금흐름")
        elif ocf_ratio < 0.5:
            score -= 1

    # 배당 (안정성 지표)
    div_yield = m.get('dividend_yield')
    if div_yield and div_yield > 0.02:
        score += 1
        if div_yield > 0.035:
            factors.append(f"안정적 배당 ({div_yield*100:.1f}%)")

    # 기관/내부자 보유 비율 - 새로 추가
    held_insiders = m.get('held_percent_insiders')
    held_institutions = m.get('held_percent_institutions')
    if held_institutions and held_institutions > 0.7:
        score += 1  # 기관 보유 비율 높으면 안정적
    if held_insiders and held_insiders > 0.1:
        score += 1  # 내부자 보유 비율 높으면 경영진 확신

    return score, factors


# ============================================================================
# 센티먼트 분석 (Peter Lynch, News Sentiment 스타일)
# ============================================================================

# 부정적 뉴스 키워드 (원본 peter_lynch.py 참조)
NEGATIVE_KEYWORDS = [
    "lawsuit", "fraud", "negative", "downturn", "decline", "investigation",
    "recall", "bankruptcy", "layoff", "cut", "warning", "miss", "loss",
    "scandal", "probe", "fine", "penalty", "default", "downgrade"
]

# 긍정적 뉴스 키워드
POSITIVE_KEYWORDS = [
    "beat", "exceed", "growth", "profit", "upgrade", "record", "expansion",
    "innovation", "breakthrough", "partnership", "acquisition", "dividend",
    "buyback", "raise", "strong", "surge", "rally", "outperform"
]


def calculate_sentiment_score(news_items: list) -> tuple:
    """
    뉴스 센티먼트 점수 계산 (Peter Lynch 스타일) - 개선된 버전

    개선 사항:
    - summary 필드도 분석에 포함 (title + summary 결합)
    - 더 많은 뉴스 분석 (limit 20 → 50)
    - 가중치 적용: summary에서 발견된 키워드는 1.5배 가중치

    Returns:
        (score, factors): 0-10 범위의 점수와 주요 요인 리스트
    """
    if not news_items:
        return 5, ["뉴스 데이터 없음 (중립)"]

    positive_score = 0
    negative_score = 0
    news_with_keywords = 0

    for item in news_items:
        title = (item.get("title") or "").lower()
        summary = (item.get("summary") or "").lower()

        # 제목에서 키워드 검색
        title_negative = any(word in title for word in NEGATIVE_KEYWORDS)
        title_positive = any(word in title for word in POSITIVE_KEYWORDS)

        # 요약에서 키워드 검색 (1.5배 가중치)
        summary_negative = any(word in summary for word in NEGATIVE_KEYWORDS)
        summary_positive = any(word in summary for word in POSITIVE_KEYWORDS)

        # 점수 계산
        if title_negative:
            negative_score += 1
            news_with_keywords += 1
        if summary_negative:
            negative_score += 0.5  # summary는 0.5 가중치
            news_with_keywords += 1

        if title_positive:
            positive_score += 1
            news_with_keywords += 1
        if summary_positive:
            positive_score += 0.5  # summary는 0.5 가중치
            news_with_keywords += 1

    total = len(news_items)
    factors = []

    # 점수 계산
    if total == 0:
        return 5, ["뉴스 없음"]

    # 분석된 뉴스 수 기반 비율 계산
    total_score = positive_score + negative_score
    if total_score > 0:
        negative_ratio = negative_score / total_score
        positive_ratio = positive_score / total_score
    else:
        negative_ratio = 0
        positive_ratio = 0

    # 뉴스 커버리지 (키워드가 있는 뉴스 비율)
    coverage_ratio = news_with_keywords / total if total > 0 else 0

    if negative_ratio > 0.6:
        # 60% 이상 부정적 → 낮은 점수
        score = 2
        factors.append(f"부정적 뉴스 우세 ({negative_score:.1f}점)")
    elif negative_ratio > 0.4:
        score = 4
        factors.append(f"부정적 뉴스 다수 ({negative_score:.1f}점)")
    elif positive_ratio > 0.6:
        score = 9
        factors.append(f"긍정적 뉴스 우세 ({positive_score:.1f}점)")
    elif positive_ratio > 0.4:
        score = 7
        factors.append(f"긍정적 뉴스 다수 ({positive_score:.1f}점)")
    else:
        score = 5
        factors.append("뉴스 센티먼트 중립")

    # 분석된 뉴스 수 정보 추가
    factors.append(f"분석 뉴스: {total}개")

    return score, factors


def calculate_insider_activity_score(insider_trades: list) -> tuple:
    """
    내부자 거래 점수 계산 (Peter Lynch 스타일) - 개선된 버전

    개선 사항:
    - 거래 금액(transaction_value) 기반 가중치 적용
    - 더 많은 거래 데이터 분석 (limit 50 → 100)
    - Direct vs Indirect 소유권 구분
    - 대규모 매수/매도에 추가 가중치

    내부자 매수 → 긍정 신호
    내부자 매도 → 부정 신호 (단, 일반적인 매도는 중립)

    Returns:
        (score, factors): 0-10 범위의 점수와 주요 요인 리스트
    """
    if not insider_trades:
        return 5, ["내부자 거래 데이터 없음 (중립)"]

    buy_count = 0
    sell_count = 0
    buy_value = 0
    sell_value = 0
    direct_buys = 0  # Direct ownership 매수

    for trade in insider_trades:
        tx_type = str(trade.get("transaction_type") or "").lower()
        shares = trade.get("shares")
        value = trade.get("value") or trade.get("transaction_value") or 0
        ownership = str(trade.get("ownership_type") or "").lower()

        # 거래 금액 절대값
        try:
            value = abs(float(value)) if value else 0
        except (TypeError, ValueError):
            value = 0

        # 거래 유형 판단
        is_buy = False
        is_sell = False

        if "buy" in tx_type or "purchase" in tx_type or "acquisition" in tx_type:
            is_buy = True
        elif "sale" in tx_type or "sell" in tx_type or "sold" in tx_type:
            is_sell = True
        elif shares is not None:
            # shares가 양수면 매수, 음수면 매도
            try:
                shares_val = float(shares)
                if shares_val > 0:
                    is_buy = True
                elif shares_val < 0:
                    is_sell = True
            except (TypeError, ValueError):
                pass

        if is_buy:
            buy_count += 1
            buy_value += value
            if "direct" in ownership:
                direct_buys += 1
        elif is_sell:
            sell_count += 1
            sell_value += value

    total_count = buy_count + sell_count
    total_value = buy_value + sell_value
    factors = []

    if total_count == 0:
        return 5, ["유효한 내부자 거래 없음"]

    # 건수 기반 비율
    buy_count_ratio = buy_count / total_count

    # 금액 기반 비율 (금액 데이터가 있는 경우)
    buy_value_ratio = buy_value / total_value if total_value > 0 else buy_count_ratio

    # 최종 비율 (건수 50% + 금액 50%)
    if total_value > 0:
        buy_ratio = (buy_count_ratio * 0.5) + (buy_value_ratio * 0.5)
    else:
        buy_ratio = buy_count_ratio

    # 점수 계산
    if buy_ratio > 0.7:
        score = 9
        factors.append(f"강한 내부자 매수 ({buy_count}건)")
    elif buy_ratio > 0.5:
        score = 7
        factors.append(f"내부자 순매수 ({buy_count}건 매수)")
    elif buy_ratio > 0.3:
        score = 5
        factors.append("내부자 거래 혼재")
    else:
        score = 3
        factors.append(f"내부자 매도 우위 ({sell_count}건)")

    # 대규모 거래 보너스/페널티
    if buy_value > 1_000_000:  # $1M 이상 매수
        score = min(10, score + 1)
        factors.append(f"대규모 매수 (${buy_value/1_000_000:.1f}M)")
    elif sell_value > 5_000_000:  # $5M 이상 매도
        score = max(1, score - 1)
        factors.append(f"대규모 매도 (${sell_value/1_000_000:.1f}M)")

    # Direct ownership 매수 보너스
    if direct_buys > 2:
        score = min(10, score + 0.5)
        factors.append(f"직접소유 매수 {direct_buys}건")

    # 분석된 거래 수 정보
    factors.append(f"총 {total_count}건 분석")

    return score, factors


# ============================================================================
# 투자자 스타일별 점수 (원본 에이전트 로직 반영)
# ============================================================================

def calculate_buffett_score(metrics, growth_score, quality_score, safety_score) -> float:
    """
    Warren Buffett 스타일 점수 (moat + margin of safety)
    - 높은 ROE + 낮은 부채 + 일관된 수익성
    """
    if not metrics:
        return 0

    m = metrics[0]
    score = 0

    # ROE > 15% (버핏의 핵심 기준)
    roe = m.get('return_on_equity')
    if roe and roe > 0.15:
        score += 3
    elif roe and roe > 0.10:
        score += 1

    # 낮은 부채
    de = m.get('debt_to_equity')
    if de is not None and de < 0.5:
        score += 2

    # 영업 마진 > 15%
    op_margin = m.get('operating_margin')
    if op_margin and op_margin > 0.15:
        score += 2

    # 품질과 안전성 가중
    score += quality_score * 0.2 + safety_score * 0.1

    return min(10, score)


def calculate_lynch_score(metrics, growth_score, sentiment_score, insider_score) -> float:
    """
    Peter Lynch 스타일 점수 (GARP + PEG)
    - PEG < 1이 핵심
    - 성장 + 센티먼트 중시
    """
    if not metrics:
        return 0

    m = metrics[0]
    score = 0

    # PEG 비율 (Lynch의 핵심 지표)
    peg = m.get('peg_ratio')
    if peg:
        if 0 < peg < 1:
            score += 4
        elif 0 < peg < 1.5:
            score += 2
        elif 0 < peg < 2:
            score += 1

    # 성장 점수 반영
    score += growth_score * 0.3

    # 센티먼트와 내부자 활동 반영
    score += sentiment_score * 0.1 + insider_score * 0.1

    return min(10, score)


def calculate_graham_score(metrics) -> float:
    """
    Ben Graham 스타일 점수 (Deep Value)
    - 낮은 P/E, 낮은 P/B, NCAV
    """
    if not metrics:
        return 0

    m = metrics[0]
    score = 0

    # P/E < 15 (Graham Number)
    pe = m.get('price_to_earnings_ratio')
    if pe:
        if 0 < pe < 10:
            score += 4
        elif 0 < pe < 15:
            score += 2

    # P/B < 1.5
    pb = m.get('price_to_book_ratio')
    if pb:
        if 0 < pb < 1:
            score += 3
        elif 0 < pb < 1.5:
            score += 2

    # 유동비율 > 2
    cr = m.get('current_ratio')
    if cr and cr > 2:
        score += 2

    return min(10, score)


def calculate_munger_score(metrics, quality_score) -> float:
    """
    Charlie Munger 스타일 점수 (Quality + ROIC)
    - ROIC > 15% + 이해 가능한 비즈니스
    """
    if not metrics:
        return 0

    m = metrics[0]
    score = 0

    # ROE > 20% (Munger는 높은 기준)
    roe = m.get('return_on_equity')
    if roe:
        if roe > 0.20:
            score += 4
        elif roe > 0.15:
            score += 2

    # 영업 마진 > 20%
    op_margin = m.get('operating_margin')
    if op_margin and op_margin > 0.20:
        score += 2

    # 품질 점수 반영
    score += quality_score * 0.4

    return min(10, score)


def calculate_wood_score(metrics, growth_score) -> float:
    """
    Cathie Wood 스타일 점수 (Disruptive Innovation)
    - 고성장 + 혁신 잠재력
    """
    if not metrics:
        return 0

    m = metrics[0]
    score = 0

    # 매출 성장 > 25%
    rev_growth = m.get('revenue_growth')
    if rev_growth:
        if rev_growth > 0.40:
            score += 4
        elif rev_growth > 0.25:
            score += 3
        elif rev_growth > 0.15:
            score += 1

    # 성장 점수 강하게 반영
    score += growth_score * 0.5

    # 고 P/E도 허용 (성장주 특성)
    pe = m.get('price_to_earnings_ratio')
    if pe and pe > 50:
        score -= 1  # 너무 비싸면 약간 감점

    return min(10, max(0, score))


def calculate_druckenmiller_score(momentum_score, growth_score) -> float:
    """
    Stanley Druckenmiller 스타일 점수 (Macro + Momentum)
    - 강한 모멘텀 + 매크로 트렌드
    """
    # 모멘텀 중심
    score = momentum_score * 0.6 + growth_score * 0.3
    return min(10, score)


def calculate_burry_score(metrics, value_score) -> float:
    """
    Michael Burry 스타일 점수 (Deep Value + Contrarian)
    - 극단적 저평가 + 자산 기반 가치
    """
    if not metrics:
        return 0

    m = metrics[0]
    score = 0

    # 매우 낮은 P/E (역발상 관점)
    pe = m.get('price_to_earnings_ratio')
    if pe:
        if 0 < pe < 8:
            score += 4
        elif 0 < pe < 12:
            score += 2

    # 낮은 P/B (자산 가치)
    pb = m.get('price_to_book_ratio')
    if pb:
        if 0 < pb < 0.8:
            score += 3
        elif 0 < pb < 1.2:
            score += 1

    # 가치 점수 반영
    score += value_score * 0.3

    return min(10, score)


# 투자자별 가중치 (원본 ensemble_analyzer.py 참조)
INVESTOR_WEIGHTS = {
    "buffett": 1.0,
    "munger": 0.95,
    "damodaran": 0.90,
    "lynch": 0.85,
    "graham": 0.85,
    "fisher": 0.82,
    "druckenmiller": 0.80,
    "pabrai": 0.78,
    "burry": 0.75,
    "ackman": 0.75,
    "jhunjhunwala": 0.72,
    "wood": 0.70,
}


def analyze_single_ticker(ticker, end_date, prefetched_prices=None, strategy="fundamental"):
    """
    단일 종목 종합 분석 (앙상블 투자자 점수 포함)

    Args:
        ticker: 종목 티커
        end_date: 분석 기준일
        prefetched_prices: 미리 배치로 가져온 가격 데이터 (선택사항)
        strategy: 분석 전략 (fundamental, momentum, hybrid)
    """
    try:
        # 1. 재무 지표 수집
        metrics = get_financial_metrics(ticker, end_date, period="annual", limit=2)

        if not metrics:
            return None

        # 2. 가격 데이터: 미리 가져온 데이터 사용 또는 개별 조회
        if prefetched_prices is not None:
            prices = prefetched_prices
        else:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            start_dt = end_dt - timedelta(days=90)
            prices = get_prices(ticker, start_dt.strftime("%Y-%m-%d"), end_date)

        # 3. 내부자 거래 데이터 (Peter Lynch 스타일)
        insider_trades = get_insider_trades(ticker, end_date, limit=50)

        # 4. 뉴스 데이터 (Sentiment 분석)
        company_news = get_company_news(ticker, end_date, limit=20)

        # 시가총액 (metrics에서 추출)
        market_cap = metrics[0].get('market_cap')
        cap_category, cap_display = get_market_cap_category(market_cap)

        # ========================================
        # 기본 팩터별 점수 계산
        # ========================================
        value_score, value_factors = calculate_value_score(metrics)
        growth_score, growth_factors = calculate_growth_score(metrics)
        quality_score, quality_factors = calculate_quality_score(metrics)
        momentum_score, momentum_factors = calculate_momentum_score(prices)
        safety_score, safety_factors = calculate_safety_score(metrics)

        # 센티먼트 & 내부자 점수 (새로 추가)
        sentiment_score, sentiment_factors = calculate_sentiment_score(company_news)
        insider_score, insider_factors = calculate_insider_activity_score(insider_trades)

        # 시가총액 기반 보너스
        size_bonus, size_factors = calculate_size_bonus(market_cap, growth_score)

        # ========================================
        # 투자자 스타일별 점수 계산 (앙상블)
        # ========================================
        investor_scores = {
            "buffett": calculate_buffett_score(metrics, growth_score, quality_score, safety_score),
            "munger": calculate_munger_score(metrics, quality_score),
            "graham": calculate_graham_score(metrics),
            "lynch": calculate_lynch_score(metrics, growth_score, sentiment_score, insider_score),
            "wood": calculate_wood_score(metrics, growth_score),
            "druckenmiller": calculate_druckenmiller_score(momentum_score, growth_score),
            "burry": calculate_burry_score(metrics, value_score),
        }

        # ========================================
        # 앙상블 가중 점수 계산
        # ========================================
        ensemble_weighted_sum = 0
        ensemble_total_weight = 0

        for investor, inv_score in investor_scores.items():
            weight = INVESTOR_WEIGHTS.get(investor, 0.5)
            ensemble_weighted_sum += inv_score * weight
            ensemble_total_weight += weight

        ensemble_score = ensemble_weighted_sum / ensemble_total_weight if ensemble_total_weight > 0 else 0

        # 기본 팩터 가중 점수 (펀더멘털)
        factor_score = (
            value_score * FACTOR_WEIGHTS["value"] +
            growth_score * FACTOR_WEIGHTS["growth"] +
            quality_score * FACTOR_WEIGHTS["quality"] +
            momentum_score * FACTOR_WEIGHTS["momentum"] +
            safety_score * FACTOR_WEIGHTS["safety"] +
            sentiment_score * FACTOR_WEIGHTS["sentiment"] +
            insider_score * FACTOR_WEIGHTS["insider"]
        )

        # 강화된 모멘텀 점수 (0-10 스케일)
        enhanced_momentum_score, momentum_details = calculate_enhanced_momentum_score(prices)

        # ========================================
        # 전략별 최종 점수 계산
        # ========================================
        fundamental_score = ensemble_score * 0.6 + factor_score * 0.4 + size_bonus

        if strategy == "momentum":
            # 모멘텀 전략: 강화된 모멘텀 점수 중심
            total_score = enhanced_momentum_score
        elif strategy == "hybrid":
            # 하이브리드 전략: 펀더멘털 50% + 모멘텀 50%
            total_score = fundamental_score * 0.5 + enhanced_momentum_score * 0.5
        else:
            # fundamental (기본): 기존 앙상블 방식
            total_score = fundamental_score

        # 모든 요인 병합 (센티먼트, 내부자 포함)
        all_factors = (value_factors + growth_factors + quality_factors +
                      momentum_factors + safety_factors + sentiment_factors +
                      insider_factors + size_factors)

        # 예상 수익률 계산 (앙상블 기반)
        normalized = (total_score - 3) / 10
        predicted_return = max(-0.30, min(0.40, normalized * 0.35))

        # 신호 결정
        if total_score >= 8:
            signal = "strong_buy"
        elif total_score >= 5:
            signal = "buy"
        elif total_score >= 2:
            signal = "hold"
        elif total_score >= 0:
            signal = "weak_sell"
        else:
            signal = "sell"

        # 투자자 합의 분석
        bullish_investors = [k for k, v in investor_scores.items() if v >= 7]
        bearish_investors = [k for k, v in investor_scores.items() if v <= 3]

        m = metrics[0]
        return {
            "ticker": ticker,
            "total_score": round(total_score, 2),
            "ensemble_score": round(ensemble_score, 2),
            "signal": signal,
            "predicted_return_1y": round(predicted_return * 100, 1),
            "factors": all_factors[:5],
            "strategy": strategy,
            "scores": {
                "value": round(value_score, 1),
                "growth": round(growth_score, 1),
                "quality": round(quality_score, 1),
                "momentum": round(momentum_score, 1),
                "enhanced_momentum": round(enhanced_momentum_score, 1),
                "safety": round(safety_score, 1),
                "sentiment": round(sentiment_score, 1),
                "insider": round(insider_score, 1),
                "size_bonus": round(size_bonus, 1),
                "fundamental": round(fundamental_score, 2),
            },
            "momentum_details": momentum_details,
            "investor_scores": {k: round(v, 1) for k, v in investor_scores.items()},
            "investor_consensus": {
                "bullish": bullish_investors,
                "bearish": bearish_investors,
            },
            "market_cap": {
                "value": market_cap,
                "display": cap_display,
                "category": cap_category,
            },
            "metrics": {
                "pe": m.get('price_to_earnings_ratio'),
                "pb": m.get('price_to_book_ratio'),
                "roe": round(m.get('return_on_equity', 0) * 100, 1) if m.get('return_on_equity') else None,
                "revenue_growth": round(m.get('revenue_growth', 0) * 100, 1) if m.get('revenue_growth') else None,
                "peg": m.get('peg_ratio'),
            }
        }

    except Exception as e:
        return None


def run_batch_analysis(tickers, end_date, max_workers=MAX_WORKERS, strategy="fundamental"):
    """배치 분석 실행

    Args:
        tickers: 분석할 종목 리스트
        end_date: 분석 기준일
        max_workers: 병렬 처리 워커 수
        strategy: 분석 전략 (fundamental, momentum, hybrid)
    """
    results = []
    total = len(tickers)
    processed = 0
    lock = threading.Lock()

    strategy_names = {"fundamental": "펀더멘털", "momentum": "모멘텀", "hybrid": "하이브리드"}
    cache_status = "활성화" if CACHE_ENABLED else "비활성화"
    print(f"분석 시작: {total}개 종목 (Workers: {max_workers}, 캐시: {cache_status}, 전략: {strategy_names.get(strategy, strategy)})")

    # 1단계: 가격 데이터 배치 다운로드 (1회 API 호출로 모든 티커)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=90)
    start_date_str = start_dt.strftime("%Y-%m-%d")

    all_prices = batch_fetch_prices(tickers, start_date_str, end_date)

    # 2단계: 재무 지표 개별 분석 (병렬 처리)
    print(f"📈 재무 지표 분석 중... ({total}개 종목)")

    def process_with_progress(ticker):
        nonlocal processed
        # 미리 가져온 가격 데이터 전달
        prefetched_prices = all_prices.get(ticker)
        result = analyze_single_ticker(ticker, end_date, prefetched_prices=prefetched_prices, strategy=strategy)
        with lock:
            processed += 1
            if processed % 25 == 0 or processed == total:
                print(f"   진행: {processed}/{total} ({processed/total*100:.0f}%)")
        return result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_with_progress, t): t for t in tickers}

        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    # 점수순 정렬
    results.sort(key=lambda x: x['total_score'], reverse=True)

    # 순위 부여
    for i, r in enumerate(results, 1):
        r['rank'] = i

    return results


def print_results(results, top_n=30, strategy="fundamental"):
    """결과 출력 (전략별 점수 포함)"""
    strategy_labels = {
        "fundamental": "펀더멘털 분석",
        "momentum": "모멘텀 분석",
        "hybrid": "하이브리드 분석 (펀더멘털 + 모멘텀)",
    }

    print("\n" + "=" * 140)
    print(f"📈 TOP {min(top_n, len(results))} 매수 추천 종목 ({strategy_labels.get(strategy, strategy)})")
    print("=" * 140)

    if strategy == "momentum":
        print(f"{'순위':<4} {'종목':<6} {'시총':<10} {'점수':<6} {'단기M':<7} {'장기M':<7} {'RSI':<6} {'추세':<8} {'신호':<12} {'P/E':<7}")
        print("-" * 140)
    elif strategy == "hybrid":
        print(f"{'순위':<4} {'종목':<6} {'시총':<10} {'점수':<6} {'펀더':<6} {'모멘':<6} {'앙상블':<6} {'신호':<12} {'수익률':<8} {'P/E':<7} {'ROE':<7} {'강세 투자자':<20}")
        print("-" * 140)
    else:  # fundamental
        print(f"{'순위':<4} {'종목':<6} {'시총':<10} {'점수':<6} {'앙상블':<6} {'신호':<12} {'수익률':<8} {'P/E':<7} {'ROE':<7} {'강세 투자자':<20} {'주요 요인'}")
        print("-" * 140)

    for r in results[:top_n]:
        pe_str = f"{r['metrics']['pe']:.1f}" if r['metrics']['pe'] else "N/A"
        roe_str = f"{r['metrics']['roe']:.0f}%" if r['metrics']['roe'] else "N/A"
        cap_str = r.get('market_cap', {}).get('display', 'N/A')
        factors_str = ', '.join(r['factors'][:2]) if r['factors'] else '-'

        # 투자자 합의 표시
        bullish = r.get('investor_consensus', {}).get('bullish', [])
        bullish_str = ', '.join(bullish[:3]) if bullish else '-'

        ensemble_str = f"{r.get('ensemble_score', 0):.1f}"
        fund_str = f"{r.get('scores', {}).get('fundamental', 0):.1f}"
        mom_str = f"{r.get('scores', {}).get('enhanced_momentum', 0):.1f}"

        # 모멘텀 상세
        mom_details = r.get('momentum_details', {})
        short_m = f"{mom_details.get('short_momentum', 0):+.0f}%"
        long_m = f"{mom_details.get('long_momentum', 0):+.0f}%"
        rsi_str = f"{mom_details.get('rsi', 50):.0f}"
        trend_map = {"bullish": "📈상승", "bearish": "📉하락", "neutral": "➡️중립"}
        trend_str = trend_map.get(mom_details.get('trend', 'neutral'), '➡️중립')

        signal_display = {
            "strong_buy": "🟢 강력매수",
            "buy": "🔵 매수",
            "hold": "⚪ 보유",
            "weak_sell": "🟡 약한매도",
            "sell": "🔴 매도"
        }.get(r['signal'], r['signal'])

        if strategy == "momentum":
            print(f"{r['rank']:<4} {r['ticker']:<6} {cap_str:<10} {r['total_score']:<6.2f} {short_m:<7} {long_m:<7} {rsi_str:<6} {trend_str:<8} {signal_display:<12} {pe_str:<7}")
        elif strategy == "hybrid":
            print(f"{r['rank']:<4} {r['ticker']:<6} {cap_str:<10} {r['total_score']:<6.2f} {fund_str:<6} {mom_str:<6} {ensemble_str:<6} {signal_display:<12} {r['predicted_return_1y']:>+5.1f}%   {pe_str:<7} {roe_str:<7} {bullish_str:<20}")
        else:  # fundamental
            print(f"{r['rank']:<4} {r['ticker']:<6} {cap_str:<10} {r['total_score']:<6.2f} {ensemble_str:<6} {signal_display:<12} {r['predicted_return_1y']:>+5.1f}%   {pe_str:<7} {roe_str:<7} {bullish_str:<20} {factors_str[:35]}")

    # 통계 출력
    buy_signals = [r for r in results if r['signal'] in ['strong_buy', 'buy']]
    sell_signals = [r for r in results if r['signal'] in ['weak_sell', 'sell']]

    # 시가총액 카테고리별 분류
    cap_categories = {"mega": [], "large": [], "mid": [], "small": [], None: []}
    for r in buy_signals:
        cat = r.get('market_cap', {}).get('category')
        cap_categories[cat].append(r)

    print("\n" + "=" * 130)
    print(f"📊 분석 요약")
    print(f"   - 총 분석 종목: {len(results)}개")
    print(f"   - 매수 추천 (strong_buy + buy): {len(buy_signals)}개")
    print(f"   - 매도/회피 권장: {len(sell_signals)}개")
    if buy_signals:
        avg_return = sum(r['predicted_return_1y'] for r in buy_signals) / len(buy_signals)
        avg_ensemble = sum(r.get('ensemble_score', 0) for r in buy_signals) / len(buy_signals)
        print(f"   - 매수 추천 종목 평균 예상 수익률: {avg_return:+.1f}%")
        print(f"   - 매수 추천 종목 평균 앙상블 점수: {avg_ensemble:.2f}")

    # 투자자별 강세 종목 분석
    print(f"\n👥 투자자별 강세 종목 (점수 ≥ 7)")
    investor_picks = {}
    for r in results[:50]:  # 상위 50개 종목에서 분석
        for investor in r.get('investor_consensus', {}).get('bullish', []):
            if investor not in investor_picks:
                investor_picks[investor] = []
            investor_picks[investor].append(r['ticker'])

    investor_names = {
        "buffett": "Warren Buffett",
        "munger": "Charlie Munger",
        "graham": "Ben Graham",
        "lynch": "Peter Lynch",
        "wood": "Cathie Wood",
        "druckenmiller": "Druckenmiller",
        "burry": "Michael Burry",
    }

    for inv_key, inv_name in investor_names.items():
        picks = investor_picks.get(inv_key, [])
        if picks:
            print(f"   - {inv_name}: {', '.join(picks[:5])}" + (f" 외 {len(picks)-5}개" if len(picks) > 5 else ""))

    # 시가총액별 매수 추천 분포
    print(f"\n📏 시가총액별 매수 추천 분포")
    cap_labels = {"mega": "메가캡 (>$200B)", "large": "대형주 ($10B-$200B)", "mid": "중형주 ($2B-$10B)", "small": "소형주 (<$2B)"}
    for cat, label in cap_labels.items():
        count = len(cap_categories.get(cat, []))
        if count > 0:
            tickers = ', '.join([r['ticker'] for r in cap_categories[cat][:5]])
            suffix = f" 외 {count-5}개" if count > 5 else ""
            print(f"   - {label}: {count}개 ({tickers}{suffix})")


def main():
    parser = argparse.ArgumentParser(
        description="종목 분석 및 1년 후 수익률 예측",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 특정 종목 분석
  uv run python analyze_stocks.py --tickers AAPL,GOOGL,MSFT

  # S&P 500 분석 (상위 30개)
  uv run python analyze_stocks.py --index sp500 --top 30

  # NASDAQ 100 분석
  uv run python analyze_stocks.py --index nasdaq100 --top 20

  # 결과 저장
  uv run python analyze_stocks.py --index sp500 --output results.json
        """
    )
    parser.add_argument("--tickers", type=str, help="분석할 종목 (콤마 구분)")
    parser.add_argument("--index", type=str, choices=["sp500", "nasdaq100"], help="인덱스 전체 분석")
    parser.add_argument("--top", type=int, default=30, help="상위 N개 출력 (기본: 30)")
    parser.add_argument("--strategy", type=str, default="fundamental",
                       choices=["fundamental", "momentum", "hybrid"],
                       help="분석 전략: fundamental(펀더멘털), momentum(모멘텀), hybrid(혼합) (기본: fundamental)")
    parser.add_argument("--sort-by-cap", action="store_true",
                       help="시가총액 기준으로 정렬 후 분석 (--top과 함께 사용 권장)")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help=f"병렬 처리 워커 수 (기본: {MAX_WORKERS})")
    parser.add_argument("--output", type=str, help="결과 저장 파일 (JSON)")
    parser.add_argument("--period", type=str, default=DEFAULT_PERIOD, help="예측 기간 (기본: 1Y)")
    parser.add_argument("--no-cache", action="store_true", help="캐시 사용 안 함 (항상 API 호출)")
    parser.add_argument("--clear-cache", action="store_true", help="캐시 삭제 후 종료")
    parser.add_argument("--cache-stats", action="store_true", help="캐시 통계 출력 후 종료")
    parser.add_argument("--update-tickers", action="store_true", help="Wikipedia에서 최신 티커 목록 갱신")

    args = parser.parse_args()

    # 캐시 관련 명령 처리
    if args.clear_cache:
        clear_cache()
        sys.exit(0)

    if args.cache_stats:
        stats = get_cache_stats()
        print(f"\n📦 캐시 통계")
        print(f"   - 캐시 파일 수: {stats['total_files']}개")
        print(f"   - 캐시 크기: {stats['total_size_mb']} MB")
        print(f"   - 캐시된 날짜: {', '.join(stats['dates'][:5]) if stats['dates'] else '없음'}")
        sys.exit(0)

    # 캐시 비활성화
    global CACHE_ENABLED
    if args.no_cache:
        CACHE_ENABLED = False
        print("⚠️  캐시 비활성화됨 - 모든 데이터를 API에서 가져옵니다.")

    # 종목 리스트 결정
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(',')]
    elif args.index:
        # --update-tickers 옵션 시 티커 캐시 무시
        use_ticker_cache = CACHE_ENABLED and not args.update_tickers
        tickers = get_index_tickers(args.index, use_cache=use_ticker_cache)
    else:
        print("오류: --tickers 또는 --index 중 하나를 지정해야 합니다.")
        parser.print_help()
        sys.exit(1)

    # --sort-by-cap: 시가총액 기준으로 정렬
    if args.sort_by_cap and tickers:
        tickers = sort_tickers_by_market_cap(tickers, top_n=args.top if args.top > 0 else 0)
    elif args.top > 0 and len(tickers) > args.top:
        # --top 옵션만 사용 시 기존 순서에서 상위 N개
        tickers = tickers[:args.top]

    end_date = datetime.now().strftime("%Y-%m-%d")
    strategy_names = {"fundamental": "펀더멘털", "momentum": "모멘텀", "hybrid": "하이브리드"}

    print(f"\n{'='*60}")
    print(f"🔍 AI Hedge Fund - 종목 분석 시스템 (Yahoo Finance)")
    print(f"{'='*60}")
    print(f"분석 날짜: {end_date}")
    print(f"예측 기간: {args.period}")
    print(f"분석 전략: {strategy_names.get(args.strategy, args.strategy)}")
    print(f"대상 종목: {len(tickers)}개")
    print()

    # 분석 실행
    results = run_batch_analysis(tickers, end_date, args.workers, strategy=args.strategy)

    if not results:
        print("분석 결과가 없습니다.")
        sys.exit(1)

    # 결과 출력
    print_results(results, args.top, strategy=args.strategy)

    # 캐시 통계 출력
    if CACHE_ENABLED:
        total_requests = cache_stats["hits"] + cache_stats["misses"]
        if total_requests > 0:
            hit_rate = cache_stats["hits"] / total_requests * 100
            print(f"\n💾 캐시 통계: {cache_stats['hits']}/{total_requests} 히트 ({hit_rate:.0f}%), API 호출 {cache_stats['misses']}회 절감")

    # 파일 저장
    strategy_methods = {
        "fundamental": "Ensemble multi-factor analysis (Value + Growth + Quality + Momentum + Safety)",
        "momentum": "Enhanced momentum analysis (Short/Long momentum + RSI + Trend)",
        "hybrid": "Hybrid analysis (50% Fundamental + 50% Enhanced Momentum)",
    }
    if args.output:
        output_data = {
            "analysis_date": end_date,
            "prediction_period": args.period,
            "strategy": args.strategy,
            "total_analyzed": len(results),
            "methodology": strategy_methods.get(args.strategy, "Multi-factor analysis"),
            "factor_weights": FACTOR_WEIGHTS,
            "rankings": results
        }
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"\n결과 저장됨: {args.output}")


if __name__ == "__main__":
    main()
