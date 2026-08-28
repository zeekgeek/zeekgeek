"""Default watchlists for crypto and equity market health."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StockSymbol:
    symbol: str
    label: str
    category: str


STOCK_WATCHLIST: tuple[StockSymbol, ...] = (
    StockSymbol("SPY", "S&P 500", "index"),
    StockSymbol("QQQ", "Nasdaq 100", "index"),
    StockSymbol("DIA", "Dow Jones", "index"),
    StockSymbol("IWM", "Russell 2000", "index"),
    StockSymbol("^VIX", "VIX", "volatility"),
    StockSymbol("AAPL", "Apple", "mega-cap"),
    StockSymbol("MSFT", "Microsoft", "mega-cap"),
    StockSymbol("NVDA", "NVIDIA", "mega-cap"),
    StockSymbol("GLD", "Gold ETF", "macro"),
    StockSymbol("TLT", "20Y Treasury", "macro"),
)

CRYPTO_PER_PAGE = 20
