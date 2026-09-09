"""Capture independent research inputs; does not use predict scores or opinions."""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '.agents/skills/predict/scripts'))
import korean_data_fetcher as kr

spec = importlib.util.spec_from_file_location('independent_fetcher', ROOT / '.agents/skills/investor-analysis/scripts/data_fetcher.py')
ia = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ia)
spec2 = importlib.util.spec_from_file_location('portfolio_generator', ROOT / '.agents/skills/portfolio-report/scripts/generate_portfolio_report.py')
pr = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(pr)
AS_OF = '2026-09-09'


def dump(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def number(value):
    try:
        result = float(str(value).replace(',', ''))
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


RULES = {
    'revenue': (['IS', 'CIS'], ['ifrs-full_Revenue'], ['매출액', '수익(매출액)', '영업수익', '매출']),
    'operating_income': (['IS', 'CIS'], ['dart_OperatingIncomeLoss'], ['영업이익', '영업이익(손실)']),
    'net_income': (['IS', 'CIS'], ['ifrs-full_ProfitLoss'], ['당기순이익', '당기순이익(손실)', '반기순이익', '반기순이익(손실)']),
    'assets': (['BS'], ['ifrs-full_Assets'], ['자산총계']),
    'liabilities': (['BS'], ['ifrs-full_Liabilities'], ['부채총계']),
    'equity': (['BS'], ['ifrs-full_Equity'], ['자본총계']),
    'cash': (['BS'], ['ifrs-full_CashAndCashEquivalents'], ['현금및현금성자산']),
    'operating_cash_flow': (['CF'], ['ifrs-full_CashFlowsFromUsedInOperatingActivities'], ['영업활동현금흐름', '영업활동으로인한현금흐름', '영업활동으로부터의현금흐름']),
    'ppe_acquisitions': (['CF'], ['ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities'], ['유형자산의취득', '유형자산취득']),
    'intangible_acquisitions': (['CF'], ['ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities'], ['무형자산의취득', '무형자산취득']),
    'rd_expense': (['IS', 'CIS'], ['dart_ResearchAndDevelopmentExpenses'], ['경상연구개발비', '연구개발비']),
}


def summarize_rows(rows, annual):
    periods = [('2025', 'thstrm_amount'), ('2024', 'frmtrm_amount'), ('2023', 'bfefrmtrm_amount')] if annual else [('2026H1', 'thstrm_amount'), ('2025H1', 'frmtrm_amount')]
    result = {period: {} for period, _ in periods}
    matched = {}
    for key, (sections, ids, names) in RULES.items():
        candidates = [r for r in rows if r.get('sj_div') in sections and r.get('account_id') in ids]
        if not candidates:
            candidates = [r for r in rows if r.get('sj_div') in sections and str(r.get('account_nm', '')).replace(' ', '') in names]
        # Duplicated IS/CIS identical figures are allowed; conflicting matches stay missing.
        matched[key] = [{'account_id': r.get('account_id'), 'account_nm': r.get('account_nm'), 'sj_div': r.get('sj_div')} for r in candidates]
        for period, col in periods:
            values = []
            for r in candidates:
                actual_col = col
                if not annual:
                    if r.get('sj_div') in ['IS', 'CIS']:
                        actual_col = 'thstrm_add_amount' if period == '2026H1' else 'frmtrm_add_amount'
                    elif period == '2025H1' and r.get('sj_div') == 'CF':
                        actual_col = 'frmtrm_q_amount'
                    elif period == '2025H1' and r.get('sj_div') == 'BS':
                        # Prior BS is December 2025, not June 2025.
                        continue
                v = number(r.get(actual_col))
                if v is not None:
                    values.append(v)
            unique = set(values)
            result[period][key] = unique.pop() if len(unique) == 1 else None
    for period, vals in result.items():
        rev, op = vals.get('revenue'), vals.get('operating_income')
        vals['operating_margin'] = op / rev if op is not None and rev is not None and rev > 0 else None
        cf, ppe, intangible = (vals.get(x) for x in ['operating_cash_flow', 'ppe_acquisitions', 'intangible_acquisitions'])
        vals['cfo_minus_ppe'] = cf - abs(ppe) if cf is not None and ppe is not None else None
        vals['fcf_after_ppe_and_intangibles'] = cf - abs(ppe) - abs(intangible) if all(x is not None for x in [cf, ppe, intangible]) else None
    return {'periods': result, 'matched_accounts': matched}


def collect(stock):
    ticker = stock['ticker']
    record = {'ticker': ticker, 'company_name': stock.get('company_name'), 'analysis_date': AS_OF,
              'observed_at': datetime.now(timezone.utc).isoformat(), 'data_quality': 'partial',
              'source_notes': ['Predict scores and investor opinions are not included.',
                               'Valuation is Naver current snapshot fallback; its earnings period is not assumed to equal 2025 annual growth.',
                               'KRX market capitalization and universe use 2026-09-08 close; prices are separately dated.',
                               'DART extracts are current filed snapshots, not a vintage archive or OOS evidence.',
                               'Null means missing or ambiguous, never zero.'], 'statements': {}}
    metrics = ia.get_financial_metrics(ticker, AS_OF, period='annual', limit=2)
    record['metrics'] = metrics[0] if metrics else {}
    record['sector'] = pr.fetch_sector(ticker)
    record['sector_provider'] = 'Yahoo Finance current metadata' if record['sector'] != 'Unknown' else 'unavailable'
    dart = kr._get_dart_reader()
    for label, year, report_code in [('annual_2025', 2025, '11011'), ('half_year_2026', 2026, '11012')]:
        entry = {'provider': 'OpenDART', 'business_year': year, 'report_code': report_code, 'as_of': AS_OF}
        for fs_div in ['CFS', 'OFS']:
            try:
                kr._dart_rate_limit()
                df = dart.finstate_all(ticker, year, reprt_code=report_code, fs_div=fs_div)
                if df is None or df.empty:
                    continue
                # pandas serialization converts NaN to JSON null.
                rows = json.loads(df.to_json(orient='records', force_ascii=False))
                valid = [r for r in rows if str(r.get('rcept_no', ''))[:8].isdigit() and str(r['rcept_no'])[:8] <= AS_OF.replace('-', '')]
                receipts = sorted(set(str(r['rcept_no']) for r in valid))
                entry.update(status='ready' if valid else 'unavailable', fs_div=fs_div, receipts=receipts,
                             currencies=sorted(set(str(r.get('currency')) for r in valid if r.get('currency'))),
                             source_urls=[f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={n}' for n in receipts],
                             excluded_after_cutoff_or_undated=len(rows)-len(valid),
                             **summarize_rows(valid, label == 'annual_2025'))
                dump(OUT / 'sources' / f'dart_{ticker}_{label}.json', {'metadata': entry, 'rows': valid})
                break
            except Exception as exc:
                entry.update(status='unavailable', error_type=type(exc).__name__)
        else:
            entry['status'] = 'unavailable'
        record['statements'][label] = entry
    record['valuation_source_url'] = f'https://m.stock.naver.com/stock/{ticker}/total'
    dump(OUT / 'sources' / f'company_{ticker}.json', record)
    return ticker, record


def main():
    predict = json.loads((OUT / 'krx_base.json').read_text(encoding='utf-8'))
    selected = predict['rankings'][:30]
    stocks = {}
    kr._get_dart_reader()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(collect, row) for row in selected]
        for f in as_completed(futures):
            ticker, data = f.result()
            stocks[ticker] = data
            print(f'independent sources {len(stocks)}/{len(selected)}: {ticker}', flush=True)
    packet = {'analysis_date': AS_OF, 'source': 'independent_investor_analysis_inputs',
              'selection': '30 candidates selected upstream; order sorted by ticker to avoid rank anchoring',
              'stocks': {ticker: stocks[ticker] for ticker in sorted(stocks)}}
    dump(OUT / 'investor_source_data.json', packet)
    print('Independent inputs saved. No predict scores or conclusions included.')


if __name__ == '__main__':
    main()
