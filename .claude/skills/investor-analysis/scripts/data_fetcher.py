#!/usr/bin/env python3
"""
Financial Data Fetcher (Yahoo Finance / 한국 DART+PyKRX 버전)

yfinance 라이브러리를 사용하여 투자 분석에 필요한 데이터를 수집합니다.
한국 주식(6자리 숫자 종목코드)은 자동으로 DART + PyKRX로 라우팅됩니다.
"""
import sys
import os
import argparse
import json
from datetime import datetime, timedelta
from typing import Optional

try:
    import yfinance as yf
except ImportError:
    print("yfinance가 설치되지 않았습니다. 설치: pip install yfinance")
    sys.exit(1)

# 한국 주식 지원을 위해 profit-predictor의 유틸리티 가져오기
_kr_utils_loaded = False
try:
    _skills_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _predictor_scripts = os.path.join(_skills_dir, "profit-predictor", "scripts")
    if _predictor_scripts not in sys.path:
        sys.path.insert(0, _predictor_scripts)
    from ticker_utils import is_korean_ticker, normalize_korean_ticker
    _kr_utils_loaded = True
except ImportError:
    # ticker_utils를 불러올 수 없으면 한국 주식 지원 비활성화
    def is_korean_ticker(ticker):
        return False
    def normalize_korean_ticker(ticker):
        return ticker


def _calculate_derived_metrics(stock, info: dict) -> dict:
    """
    재무제표 기반 파생 지표 계산

    ROIC, Interest Coverage, Cash Ratio 등 Yahoo Finance info에서
    직접 제공하지 않는 지표들을 재무제표에서 계산합니다.
    """
    import pandas as pd

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
        try:
            ebit = None
            for ebit_name in ["EBIT", "Operating Income"]:
                if ebit_name in income_stmt.index:
                    val = income_stmt.loc[ebit_name, latest_col]
                    if pd.notna(val):
                        ebit = float(val)
                        break

            if ebit:
                tax_rate = 0.21
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

        # Operating Cash Flow Ratio
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


def get_financial_metrics(ticker: str, end_date: str = None, period: str = "annual", limit: int = 5) -> list:
    """
    재무 지표 가져오기 (Yahoo Finance / 한국 DART+PyKRX)

    한국 주식은 DART + PyKRX에서 데이터를 수집합니다.

    Returns:
        Financial Datasets API와 호환되는 형식의 dict 리스트
    """
    if is_korean_ticker(ticker):
        try:
            from korean_data_fetcher import get_financial_metrics_kr
            kr_ticker = normalize_korean_ticker(ticker)
            result = get_financial_metrics_kr(kr_ticker, end_date or datetime.now().strftime("%Y-%m-%d"))
            return [result] if result else []
        except ImportError as e:
            print(f"한국 주식 데이터 모듈 로드 실패: {e}")
            return []

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

        metrics = {
            "ticker": ticker,
            "report_period": end_date or datetime.now().strftime("%Y-%m-%d"),

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
        }

        return [metrics]
    except Exception as e:
        print(f"재무 지표 조회 실패 ({ticker}): {e}")
        return []


def get_prices(ticker: str, start_date: str, end_date: str) -> list:
    """
    가격 데이터 가져오기 (Yahoo Finance / 한국 PyKRX)

    Returns:
        Financial Datasets API와 호환되는 형식의 dict 리스트
    """
    if is_korean_ticker(ticker):
        try:
            from korean_data_fetcher import get_prices_kr
            return get_prices_kr(normalize_korean_ticker(ticker), start_date, end_date)
        except ImportError as e:
            print(f"한국 주식 데이터 모듈 로드 실패: {e}")
            return []

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
        print(f"가격 데이터 조회 실패 ({ticker}): {e}")
        return []


def get_market_cap(ticker: str, end_date: str = None) -> Optional[float]:
    """시가총액 가져오기 (Yahoo Finance / 한국 PyKRX)"""
    if is_korean_ticker(ticker):
        try:
            from korean_data_fetcher import get_market_cap_kr
            return get_market_cap_kr(normalize_korean_ticker(ticker), end_date or datetime.now().strftime("%Y-%m-%d"))
        except ImportError:
            return None

    try:
        stock = yf.Ticker(ticker)
        return stock.info.get("marketCap")
    except Exception as e:
        print(f"시가총액 조회 실패 ({ticker}): {e}")
        return None


def get_insider_trades(ticker: str, end_date: str = None, limit: int = 100) -> list:
    """
    내부자 거래 데이터 가져오기 (Yahoo Finance / 한국 DART 공시)
    """
    if is_korean_ticker(ticker):
        try:
            from korean_data_fetcher import get_insider_trades_kr
            return get_insider_trades_kr(normalize_korean_ticker(ticker), end_date or datetime.now().strftime("%Y-%m-%d"), limit)
        except ImportError:
            return []

    try:
        stock = yf.Ticker(ticker)

        insider_transactions = stock.insider_transactions
        if insider_transactions is None or insider_transactions.empty:
            return []

        trades = []
        for _, row in insider_transactions.head(limit).iterrows():
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
                "ticker": ticker,
                "insider_name": row.get("Insider"),
                "insider_title": row.get("Position"),
                "transaction_type": row.get("Transaction") or row.get("Text"),
                "shares": shares,
                "value": value,
                "transaction_price_per_share": price_per_share,
                "transaction_date": str(row.get("Start Date")) if row.get("Start Date") else None,
                "filing_date": str(row.get("Start Date")) if row.get("Start Date") else None,
                "ownership_type": row.get("Ownership"),
                "filing_url": row.get("URL"),
            })

        return trades
    except Exception as e:
        print(f"내부자 거래 조회 실패 ({ticker}): {e}")
        return []


def get_company_news(ticker: str, end_date: str = None, limit: int = 100) -> list:
    """
    뉴스 데이터 가져오기 (Yahoo Finance / 한국 DART 공시)
    """
    if is_korean_ticker(ticker):
        try:
            from korean_data_fetcher import get_company_news_kr
            return get_company_news_kr(normalize_korean_ticker(ticker), end_date or datetime.now().strftime("%Y-%m-%d"), limit)
        except ImportError:
            return []

    try:
        stock = yf.Ticker(ticker)
        news = stock.news

        if not news:
            return []

        news_list = []
        for item in news[:limit]:
            # summary 추출 (여러 가능한 위치 탐색)
            summary = ""
            content = item.get("content", {})
            if isinstance(content, dict):
                summary = content.get("summary", "") or ""
            if not summary:
                summary = item.get("summary", "") or ""

            # content_type 및 thumbnail 추출
            content_type = None
            thumbnail_url = None
            if isinstance(content, dict):
                content_type = content.get("contentType")
                thumbnail = content.get("thumbnail", {})
                if isinstance(thumbnail, dict):
                    resolutions = thumbnail.get("resolutions", [])
                    if resolutions and len(resolutions) > 0:
                        thumbnail_url = resolutions[0].get("url")

            news_list.append({
                "ticker": ticker,
                "title": item.get("title"),
                "source": item.get("publisher"),
                "url": item.get("link"),
                "date": datetime.fromtimestamp(item.get("providerPublishTime", 0)).strftime("%Y-%m-%d %H:%M:%S") if item.get("providerPublishTime") else None,
                "summary": summary,
                "content_type": content_type,
                "thumbnail_url": thumbnail_url,
            })

        return news_list
    except Exception as e:
        print(f"뉴스 조회 실패 ({ticker}): {e}")
        return []


def search_line_items(ticker: str, line_items: list, end_date: str = None, period: str = "annual", limit: int = 5) -> list:
    """
    재무제표 라인 아이템 검색 (Yahoo Finance / 한국 DART)

    Financial Datasets API의 search_line_items와 유사한 인터페이스 제공.
    """
    if is_korean_ticker(ticker):
        try:
            from korean_data_fetcher import search_line_items_kr
            return search_line_items_kr(normalize_korean_ticker(ticker), line_items, end_date or datetime.now().strftime("%Y-%m-%d"), period, limit)
        except ImportError as e:
            print(f"한국 주식 데이터 모듈 로드 실패: {e}")
            return []

    try:
        stock = yf.Ticker(ticker)

        # 재무제표 가져오기
        if period == "annual":
            income_stmt = stock.financials
            balance_sheet = stock.balance_sheet
            cash_flow = stock.cashflow
        else:
            income_stmt = stock.quarterly_financials
            balance_sheet = stock.quarterly_balance_sheet
            cash_flow = stock.quarterly_cashflow

        # yfinance 필드명 매핑
        field_mapping = {
            "revenue": ["Total Revenue", "Revenue"],
            "net_income": ["Net Income", "Net Income Common Stockholders"],
            "operating_income": ["Operating Income", "EBIT"],
            "gross_profit": ["Gross Profit"],
            "free_cash_flow": ["Free Cash Flow"],
            "operating_cash_flow": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
            "capital_expenditure": ["Capital Expenditure", "Capital Expenditures"],
            "depreciation_and_amortization": ["Depreciation And Amortization", "Depreciation"],
            "total_debt": ["Total Debt"],
            "shareholders_equity": ["Stockholders Equity", "Total Stockholder Equity"],
            "total_assets": ["Total Assets"],
            "total_liabilities": ["Total Liabilities Net Minority Interest", "Total Liab"],
            "current_assets": ["Current Assets", "Total Current Assets"],
            "current_liabilities": ["Current Liabilities", "Total Current Liabilities"],
            "cash_and_equivalents": ["Cash And Cash Equivalents", "Cash"],
            "research_and_development": ["Research And Development", "Research Development"],
            "selling_general_and_administrative": ["Selling General And Administration", "Selling General And Administrative"],
        }

        results = []

        # 각 기간에 대해 데이터 수집
        all_dfs = [income_stmt, balance_sheet, cash_flow]
        periods_found = set()

        for df in all_dfs:
            if df is not None and not df.empty:
                for col in df.columns[:limit]:
                    periods_found.add(col)

        for report_period in sorted(periods_found, reverse=True)[:limit]:
            item_data = {
                "ticker": ticker,
                "report_period": report_period.strftime("%Y-%m-%d") if hasattr(report_period, 'strftime') else str(report_period),
                "period": period,
            }

            for item_name in line_items:
                value = None
                yf_names = field_mapping.get(item_name, [item_name])

                for df in all_dfs:
                    if df is None or df.empty:
                        continue
                    if report_period not in df.columns:
                        continue

                    for yf_name in yf_names:
                        if yf_name in df.index:
                            val = df.loc[yf_name, report_period]
                            if val is not None and not (isinstance(val, float) and val != val):  # NaN check
                                value = float(val)
                                break
                    if value is not None:
                        break

                item_data[item_name] = value

            results.append(item_data)

        return results
    except Exception as e:
        print(f"재무제표 조회 실패 ({ticker}): {e}")
        return []


def fetch_value_investor_data(ticker: str, end_date: str) -> dict:
    """가치 투자자(버핏, 그레이엄, 멍거, 파브라이)에게 필요한 데이터 수집."""
    metrics = get_financial_metrics(ticker, end_date)

    line_items = search_line_items(
        ticker,
        [
            "revenue", "net_income", "operating_income", "gross_profit",
            "free_cash_flow", "operating_cash_flow", "capital_expenditure",
            "depreciation_and_amortization", "total_debt", "shareholders_equity",
            "total_assets", "total_liabilities", "current_assets", "current_liabilities",
            "cash_and_equivalents",
        ],
        end_date,
        period="annual",
        limit=5,
    )

    market_cap = get_market_cap(ticker, end_date)

    return {
        "metrics": metrics,
        "line_items": line_items,
        "market_cap": market_cap,
    }


def fetch_growth_investor_data(ticker: str, end_date: str) -> dict:
    """성장 투자자(캐시우드, 린치, 피셔)에게 필요한 데이터 수집."""
    metrics = get_financial_metrics(ticker, end_date)

    line_items = search_line_items(
        ticker,
        [
            "revenue", "net_income", "gross_profit", "operating_income",
            "research_and_development", "free_cash_flow",
            "selling_general_and_administrative",
        ],
        end_date,
        period="annual",
        limit=5,
    )

    market_cap = get_market_cap(ticker, end_date)

    return {
        "metrics": metrics,
        "line_items": line_items,
        "market_cap": market_cap,
    }


def fetch_technical_data(ticker: str, end_date: str, lookback_days: int = 252) -> dict:
    """기술적 분석에 필요한 가격 데이터 수집."""
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=lookback_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    prices = get_prices(ticker, start_date, end_date)

    return {
        "prices": prices,
        "start_date": start_date,
        "end_date": end_date,
    }


def fetch_sentiment_data(ticker: str, end_date: str) -> dict:
    """센티먼트 분석에 필요한 데이터 수집."""
    insider_trades = get_insider_trades(ticker, end_date, limit=100)
    company_news = get_company_news(ticker, end_date, limit=50)

    return {
        "insider_trades": insider_trades,
        "company_news": company_news,
    }


def fetch_all_data(ticker: str, end_date: str) -> dict:
    """모든 투자자/분석가에게 필요한 전체 데이터 수집."""
    value_data = fetch_value_investor_data(ticker, end_date)
    technical_data = fetch_technical_data(ticker, end_date)
    sentiment_data = fetch_sentiment_data(ticker, end_date)

    return {
        "ticker": ticker,
        "end_date": end_date,
        "financial_metrics": value_data["metrics"],
        "line_items": value_data["line_items"],
        "market_cap": value_data["market_cap"],
        "prices": technical_data["prices"],
        "insider_trades": sentiment_data["insider_trades"],
        "company_news": sentiment_data["company_news"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch financial data for analysis (Yahoo Finance)")
    parser.add_argument("--ticker", type=str, required=True, help="Stock ticker (e.g., AAPL)")
    parser.add_argument("--end-date", type=str, default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--data-type", type=str, default="all",
                       choices=["all", "value", "growth", "technical", "sentiment"],
                       help="Type of data to fetch")

    args = parser.parse_args()

    end_date = args.end_date or datetime.now().strftime("%Y-%m-%d")

    print(f"Yahoo Finance에서 {args.ticker} 데이터 조회 중...")

    if args.data_type == "all":
        data = fetch_all_data(args.ticker, end_date)
    elif args.data_type == "value":
        data = fetch_value_investor_data(args.ticker, end_date)
    elif args.data_type == "growth":
        data = fetch_growth_investor_data(args.ticker, end_date)
    elif args.data_type == "technical":
        data = fetch_technical_data(args.ticker, end_date)
    elif args.data_type == "sentiment":
        data = fetch_sentiment_data(args.ticker, end_date)

    print(json.dumps(data, indent=2, default=str))
