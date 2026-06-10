"""KRX 데이터 클라이언트 (pykrx 래퍼) + 기술적 지표 계산."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from pykrx import stock


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _date_ago(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")


class KrxClient:
    @staticmethod
    def get_name(ticker: str) -> str:
        return stock.get_market_ticker_name(ticker)

    @staticmethod
    def get_ohlcv(ticker: str, days: int = 365) -> pd.DataFrame:
        start = _date_ago(days)
        end = _today()
        return stock.get_market_ohlcv(start, end, ticker)

    @staticmethod
    def get_market_snapshot(ticker: str) -> dict[str, Any]:
        """현재 시점의 시총·PER·PBR·거래량 등."""
        for offset in range(10):
            date = (datetime.now() - timedelta(days=offset)).strftime("%Y%m%d")
            try:
                cap_df = stock.get_market_cap(date, date, ticker)
                fund_df = stock.get_market_fundamental(date, date, ticker)
                if cap_df.empty or fund_df.empty:
                    continue
                cap = cap_df.iloc[-1]
                fund = fund_df.iloc[-1]
                return {
                    "date": date,
                    "market_cap_krw": int(cap["시가총액"]),
                    "listed_shares": int(cap["상장주식수"]),
                    "trading_volume": int(cap["거래량"]),
                    "trading_value_krw": int(cap["거래대금"]),
                    "PER": float(fund["PER"]),
                    "PBR": float(fund["PBR"]),
                    "EPS": float(fund["EPS"]),
                    "BPS": float(fund["BPS"]),
                    "DIV_yield": float(fund["DIV"]),
                    "DPS": float(fund["DPS"]),
                }
            except Exception:
                continue
        raise RuntimeError(f"종목 {ticker}의 시장 데이터를 가져올 수 없습니다.")


def compute_technical_indicators(ohlcv: pd.DataFrame) -> dict[str, Any]:
    """이동평균, RSI(14), MACD, 변동성, 52주 고저 등."""
    if ohlcv.empty:
        raise ValueError("OHLCV 데이터가 비어있습니다.")

    close = ohlcv["종가"].astype(float)
    high = ohlcv["고가"].astype(float)
    low = ohlcv["저가"].astype(float)
    volume = ohlcv["거래량"].astype(float)

    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    ma120 = close.rolling(120).mean()

    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    histogram = macd - signal

    daily_return = close.pct_change()
    volatility_20d = float(daily_return.tail(20).std() * (252**0.5) * 100)

    last_idx = -1
    current = float(close.iloc[last_idx])

    def safe_pct(window: int) -> float | None:
        if len(close) <= window:
            return None
        return float((close.iloc[last_idx] / close.iloc[last_idx - window] - 1) * 100)

    def safe_float(series: pd.Series) -> float | None:
        v = series.iloc[last_idx]
        return None if pd.isna(v) else float(v)

    tail_year = close.tail(252) if len(close) >= 252 else close

    return {
        "current_price": current,
        "ma5": safe_float(ma5),
        "ma20": safe_float(ma20),
        "ma60": safe_float(ma60),
        "ma120": safe_float(ma120),
        "rsi14": safe_float(rsi),
        "macd": safe_float(macd),
        "macd_signal": safe_float(signal),
        "macd_histogram": safe_float(histogram),
        "volatility_20d_annualized_pct": volatility_20d,
        "price_change_1d_pct": safe_pct(1),
        "price_change_1w_pct": safe_pct(5),
        "price_change_1m_pct": safe_pct(20),
        "price_change_3m_pct": safe_pct(60),
        "price_change_1y_pct": safe_pct(252),
        "high_52w": float(tail_year.max()),
        "low_52w": float(tail_year.min()),
        "high_52w_distance_pct": float((current / tail_year.max() - 1) * 100),
        "low_52w_distance_pct": float((current / tail_year.min() - 1) * 100),
        "avg_volume_20d": float(volume.tail(20).mean()),
        "avg_volume_60d": float(volume.tail(60).mean()),
    }


def ohlcv_for_chart(ohlcv: pd.DataFrame, max_points: int = 120) -> list[dict[str, Any]]:
    """차트용 최근 N일 OHLCV (Chart.js 호환 형태)."""
    if ohlcv.empty:
        return []
    tail = ohlcv.tail(max_points)
    out: list[dict[str, Any]] = []
    for idx, row in tail.iterrows():
        out.append(
            {
                "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
                "open": float(row["시가"]),
                "high": float(row["고가"]),
                "low": float(row["저가"]),
                "close": float(row["종가"]),
                "volume": int(row["거래량"]),
            }
        )
    return out
