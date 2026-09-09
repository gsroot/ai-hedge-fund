"""Archive adjusted prices for current-holdings risk estimation, not a selection backtest."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

HERE = Path(__file__).resolve().parent
START, END = '2021-09-08', '2026-09-09'
TICKERS = ['ADBE', 'INCY', 'NVDA', 'GDDY', 'SPY']


def fetch(ticker):
    frame = yf.Ticker(ticker).history(start=START, end=END, auto_adjust=False, actions=True, raise_errors=True, timeout=30)
    if frame.empty or 'Adj Close' not in frame:
        raise ValueError(f'{ticker}: missing adjusted prices')
    frame.index = pd.DatetimeIndex(frame.index.date, name='Date')
    if frame.index.duplicated().any() or frame.index.max() != pd.Timestamp('2026-09-08'):
        raise ValueError(f'{ticker}: duplicate or stale dates')
    if frame['Adj Close'].isna().any() or (frame['Adj Close'] <= 0).any():
        raise ValueError(f'{ticker}: invalid price')
    target = HERE / f'{ticker}_prices.csv'
    frame.to_csv(target)
    return ticker, {'source': f'https://finance.yahoo.com/quote/{ticker}/history/', 'rows': len(frame), 'first': str(frame.index.min().date()), 'last': str(frame.index.max().date()), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:
        metadata = dict(pool.map(fetch, TICKERS))
    result = {'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'source': 'Yahoo Finance via yfinance', 'start': START, 'end_exclusive': END, 'price_semantics': 'Adj Close, current split/dividend revisions; total-return proxy, no historical provider vintages', 'use': 'risk estimation for already-selected holdings only; no historical selection alpha claim', 'tickers': metadata}
    (HERE / 'price_manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
