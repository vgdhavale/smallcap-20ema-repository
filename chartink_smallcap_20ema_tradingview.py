"""
Create a CSV containing Smallcap stocks from the last month of a
Chartink backtest that are trading near their 20-day EMA.

The GitHub Actions workflow downloads the Chartink CSV from Google Drive,
runs this script, and commits the resulting CSV to this repository.

Install:
    pip install -r requirements.txt

Run locally:
    python chartink_smallcap_20ema_tradingview.py \
      --input "Backtest HVY @finallynitin.csv" \
      --output smallcap_stocks_near_20ema.csv
"""

from __future__ import annotations

import argparse
import random
import re
import time
from pathlib import Path
from typing import List, Optional

import pandas as pd

try:
    import yfinance as yf
except ImportError as exc:
    raise SystemExit(
        "Missing dependency. Install it with: pip install pandas yfinance openpyxl"
    ) from exc


LOOKBACK_DAYS = 30
EMA_PERIOD = 20
EMA_TOLERANCE_PERCENT = 2.0
PRICE_SOURCE_LOOKBACK_DAYS = 120

BATCH_SIZE = 12
BATCH_DELAY_SECONDS = 3.0
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2.0

TRADINGVIEW_BASE = "https://in.tradingview.com/symbols/NSE-{}"


def clean_symbol(value: object) -> str:
    symbol = str(value).strip().upper()
    symbol = symbol.replace("&", "-")
    symbol = re.sub(r"[^A-Z0-9._-]", "", symbol)
    return symbol


def tradingview_url(symbol: str) -> str:
    return TRADINGVIEW_BASE.format(symbol)


def load_chartink_candidates(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path.resolve()}")

    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [str(column).strip() for column in df.columns]

    required = {"Date", "Symbol", "Marketcapname"}
    missing = required.difference(df.columns)

    if missing:
        raise ValueError(
            f"Missing required columns: {sorted(missing)}. "
            f"Available columns: {df.columns.tolist()}"
        )

    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df["Symbol"] = df["Symbol"].map(clean_symbol)
    df["Marketcapname"] = df["Marketcapname"].astype(str).str.strip()

    df = df.dropna(subset=["Date"])
    df = df[df["Symbol"].ne("")]

    return df


def download_batch_with_retry(
    tickers: List[str],
    start: str,
    end: str,
    max_retries: int = MAX_RETRIES,
    backoff_factor: float = RETRY_BACKOFF_FACTOR,
) -> Optional[pd.DataFrame]:
    for attempt in range(max_retries + 1):
        try:
            prices = yf.download(
                tickers=tickers,
                start=start,
                end=end,
                interval="1d",
                auto_adjust=False,
                group_by="column",
                threads=True,
                progress=False,
                timeout=60,
            )

            if prices is not None and not prices.empty:
                return prices

            if attempt < max_retries:
                wait_time = backoff_factor ** attempt + random.uniform(0.5, 1.5)
                print(
                    f"    Empty response. Retrying in {wait_time:.1f}s "
                    f"({attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
                continue

            print(f"    Empty response after {max_retries} retries")
            return None

        except Exception as error:
            error_message = str(error).lower()

            retryable = any(
                phrase in error_message
                for phrase in (
                    "rate limit",
                    "too many requests",
                    "connection",
                    "timeout",
                )
            )

            if retryable and attempt < max_retries:
                wait_time = backoff_factor ** attempt + random.uniform(1, 2)
                print(
                    f"    Rate limit/error. Retrying in {wait_time:.1f}s "
                    f"({attempt + 1}/{max_retries})"
                )
                time.sleep(wait_time)
                continue

            print(f"    Failed after retries: {error}")
            return None

    return None


def download_prices_chunked(
    tickers: List[str],
    start: str,
    end: str,
    batch_size: int = BATCH_SIZE,
    batch_delay: float = BATCH_DELAY_SECONDS,
) -> pd.DataFrame:
    print(f"\nDownloading {len(tickers)} tickers in chunks of {batch_size}...")
    print(f"Date range: {start} to {end}")
    print(f"Total batches: {(len(tickers) + batch_size - 1) // batch_size}")

    all_close_data = {}

    for index in range(0, len(tickers), batch_size):
        batch_tickers = tickers[index:index + batch_size]
        batch_number = (index // batch_size) + 1
        total_batches = (len(tickers) + batch_size - 1) // batch_size

        print(
            f"\nBatch {batch_number}/{total_batches} "
            f"({len(batch_tickers)} tickers): "
            f"{batch_tickers[0]} to {batch_tickers[-1]}"
        )

        batch_data = download_batch_with_retry(batch_tickers, start, end)

        if batch_data is not None and not batch_data.empty:
            if isinstance(batch_data.columns, pd.MultiIndex):
                if "Close" in batch_data.columns.get_level_values(0).unique():
                    close_prices = batch_data["Close"]
                else:
                    print(f"    Warning: no Close prices in batch {batch_number}")
                    continue
            else:
                if "Close" in batch_data.columns:
                    close_prices = batch_data[["Close"]]
                    close_prices.columns = [batch_tickers[0]]
                else:
                    print(f"    Warning: no Close prices in batch {batch_number}")
                    continue

            close_prices.columns = [
                str(column).removesuffix(".NS").upper()
                for column in close_prices.columns
            ]

            for column in close_prices.columns:
                if column not in all_close_data:
                    all_close_data[column] = close_prices[column]

            print(
                f"    Downloaded {len(close_prices.columns)} tickers, "
                f"{len(close_prices)} days"
            )
        else:
            print(f"    Failed to download batch {batch_number}")

        if index + batch_size < len(tickers):
            delay = batch_delay + random.uniform(0.5, 1.5)
            print(f"    Waiting {delay:.1f}s before next batch...")
            time.sleep(delay)

    if not all_close_data:
        raise RuntimeError("No price data was successfully downloaded.")

    combined_close = pd.DataFrame(all_close_data)
    combined_close.index = pd.to_datetime(combined_close.index).tz_localize(None)
    combined_close = combined_close.sort_index()

    print(
        f"\nCombined {len(combined_close.columns)} tickers "
        f"with {len(combined_close)} days of data"
    )

    return combined_close


def calculate_ema_candidates(
    candidates: pd.DataFrame,
    end_date: pd.Timestamp,
    lookback_days: int = LOOKBACK_DAYS,
) -> pd.DataFrame:
    start_date = end_date - pd.Timedelta(days=lookback_days)

    recent = candidates.loc[
        (candidates["Date"] >= start_date)
        & (candidates["Date"] <= end_date)
        & candidates["Marketcapname"].str.casefold().eq("smallcap")
    ].copy()

    if recent.empty:
        print("No Smallcap candidates found in the last month.")
        return pd.DataFrame()

    recent = recent.sort_values("Date")
    symbols = sorted(recent["Symbol"].unique())
    tickers = [f"{symbol}.NS" for symbol in symbols]

    price_start = start_date - pd.Timedelta(days=PRICE_SOURCE_LOOKBACK_DAYS)
    price_end = end_date + pd.Timedelta(days=1)

    close = download_prices_chunked(
        tickers,
        price_start.strftime("%Y-%m-%d"),
        price_end.strftime("%Y-%m-%d"),
    )

    print(f"\nProcessing {len(symbols)} symbols for EMA calculation...")

    records = []

    for symbol in symbols:
        if symbol not in close.columns:
            print(f"  Warning: no price data for {symbol}")
            continue

        series = pd.to_numeric(close[symbol], errors="coerce").dropna()

        if len(series) < EMA_PERIOD:
            print(
                f"  Warning: insufficient data for {symbol} "
                f"({len(series)} days)"
            )
            continue

        ema = series.ewm(
            span=EMA_PERIOD,
            adjust=False,
            min_periods=EMA_PERIOD,
        ).mean()

        window = pd.DataFrame(
            {
                "Close": series,
                "EMA_20": ema,
            }
        ).loc[start_date:end_date]

        window = window.dropna(subset=["Close", "EMA_20"])

        if window.empty:
            continue

        latest_date = window.index[-1]
        latest = window.iloc[-1]

        distance = (
            (latest["Close"] - latest["EMA_20"])
            / latest["EMA_20"]
            * 100
        )

        if abs(distance) <= EMA_TOLERANCE_PERCENT:
            symbol_rows = recent[recent["Symbol"].eq(symbol)]
            latest_scan_date = symbol_rows["Date"].max()

            sectors = []
            if "Sector" in symbol_rows.columns:
                sectors = (
                    symbol_rows["Sector"]
                    .dropna()
                    .astype(str)
                    .unique()
                    .tolist()
                )

            records.append(
                {
                    "Symbol": symbol,
                    "Chartink_Last_Date": latest_scan_date.date(),
                    "Price_Date": pd.Timestamp(latest_date).date(),
                    "Marketcap": "Smallcap",
                    "Sector": ", ".join(sectors),
                    "Close": round(float(latest["Close"]), 2),
                    "EMA_20": round(float(latest["EMA_20"]), 2),
                    "Distance_from_20EMA_%": round(float(distance), 2),
                    "Absolute_Distance_%": round(float(abs(distance)), 2),
                    "TradingView_Link": tradingview_url(symbol),
                }
            )

    return pd.DataFrame(records)


def write_csv(result: pd.DataFrame, output: Path) -> None:
    if result.empty:
        result = pd.DataFrame(
            columns=[
                "Symbol",
                "Chartink_Last_Date",
                "Price_Date",
                "Marketcap",
                "Sector",
                "Close",
                "EMA_20",
                "Distance_from_20EMA_%",
                "Absolute_Distance_%",
                "TradingView_Link",
            ]
        )

    result = result.sort_values(
        "Absolute_Distance_%"
    ).reset_index(drop=True)

    result.to_csv(output, index=False, encoding="utf-8-sig")

    print(f"\nCSV created: {output.resolve()}")
    print(f"Stocks near 20 EMA: {len(result)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find Smallcap stocks trading near their 20-day EMA"
    )

    parser.add_argument(
        "--input",
        required=True,
        help="Path to the Chartink backtest CSV",
    )

    parser.add_argument(
        "--output",
        default="smallcap_stocks_near_20ema.csv",
        help="Output CSV file path",
    )

    args = parser.parse_args()

    input_file = Path(args.input)
    output_file = Path(args.output)

    print("=" * 80)
    print("Chartink Smallcap Stocks Near 20 EMA Analysis")
    print("=" * 80)

    source = load_chartink_candidates(input_file)
    end_date = source["Date"].max()
    start_date = end_date - pd.Timedelta(days=LOOKBACK_DAYS)

    print(
        f"\nChartink data range: "
        f"{source['Date'].min().date()} to {end_date.date()}"
    )
    print(
        f"Analyzing last {LOOKBACK_DAYS} days: "
        f"{start_date.date()} to {end_date.date()}"
    )

    result = calculate_ema_candidates(source, end_date)
    write_csv(result, output_file)


if __name__ == "__main__":
    main()
