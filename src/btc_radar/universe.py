"""Tickers and metadata for the Bitcoin market radar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

AssetKind = Literal["crypto", "index", "mega", "macro"]


@dataclass(frozen=True)
class CryptoSpec:
    coin_id: str
    symbol: str
    name: str
    is_btc: bool = False
    is_stable: bool = False


@dataclass(frozen=True)
class EquitySpec:
    symbol: str
    name: str
    kind: Literal["index", "mega", "macro"]
    yahoo: str


CRYPTO: tuple[CryptoSpec, ...] = (
    CryptoSpec("bitcoin", "BTC", "Bitcoin", is_btc=True),
    CryptoSpec("ethereum", "ETH", "Ethereum"),
    CryptoSpec("solana", "SOL", "Solana"),
    CryptoSpec("ripple", "XRP", "XRP"),
    CryptoSpec("binancecoin", "BNB", "BNB"),
    CryptoSpec("dogecoin", "DOGE", "Dogecoin"),
    CryptoSpec("cardano", "ADA", "Cardano"),
    CryptoSpec("avalanche-2", "AVAX", "Avalanche"),
    CryptoSpec("chainlink", "LINK", "Chainlink"),
    CryptoSpec("polkadot", "DOT", "Polkadot"),
    CryptoSpec("the-open-network", "TON", "Toncoin"),
    CryptoSpec("tron", "TRX", "TRON"),
    CryptoSpec("sui", "SUI", "Sui"),
    CryptoSpec("litecoin", "LTC", "Litecoin"),
    CryptoSpec("near", "NEAR", "NEAR"),
    CryptoSpec("uniswap", "UNI", "Uniswap"),
    CryptoSpec("shiba-inu", "SHIB", "Shiba Inu"),
    CryptoSpec("pepe", "PEPE", "Pepe"),
    CryptoSpec("tether", "USDT", "Tether", is_stable=True),
    CryptoSpec("usd-coin", "USDC", "USD Coin", is_stable=True),
)

EQUITIES: tuple[EquitySpec, ...] = (
    EquitySpec("SPY", "S&P 500", "index", "SPY"),
    EquitySpec("QQQ", "Nasdaq 100", "index", "QQQ"),
    EquitySpec("DIA", "Dow Jones", "index", "DIA"),
    EquitySpec("IWM", "Russell 2000", "index", "IWM"),
    EquitySpec("NVDA", "NVIDIA", "mega", "NVDA"),
    EquitySpec("AAPL", "Apple", "mega", "AAPL"),
    EquitySpec("MSFT", "Microsoft", "mega", "MSFT"),
    EquitySpec("GOOGL", "Alphabet", "mega", "GOOGL"),
    EquitySpec("AMZN", "Amazon", "mega", "AMZN"),
    EquitySpec("META", "Meta", "mega", "META"),
    EquitySpec("TSLA", "Tesla", "mega", "TSLA"),
    EquitySpec("GLD", "Gold", "macro", "GLD"),
    EquitySpec("SLV", "Silver", "macro", "SLV"),
    EquitySpec("USO", "Crude oil", "macro", "USO"),
    EquitySpec("UUP", "US Dollar", "macro", "UUP"),
    EquitySpec("VIX", "Volatility", "macro", "^VIX"),
    EquitySpec("TNX", "10Y yield", "macro", "^TNX"),
)

# Fourth halving was 2024-04-20; the fifth is estimated ~4 years later.
NEXT_HALVING = datetime(2028, 4, 17, tzinfo=UTC)

ROADMAP = (
    {
        "id": "onchain",
        "title": "On-chain pulse",
        "blurb": "Mempool fees, hash rate, and exchange netflow so you can see whether coins are moving to sell or to cold storage.",
    },
    {
        "id": "etf-flows",
        "title": "Spot ETF tape",
        "blurb": "Daily IBIT / FBTC creations and redemptions — the cleanest read on traditional-market demand for Bitcoin.",
    },
    {
        "id": "perps",
        "title": "Perp funding & OI",
        "blurb": "Funding rates and open interest across BTC/ETH perps. Crowded leverage is how cascades start.",
    },
    {
        "id": "liqs",
        "title": "Liquidation radar",
        "blurb": "A heatmap of nearby liquidation clusters so a wick is not a surprise.",
    },
    {
        "id": "stable-dry-powder",
        "title": "Stablecoin dry powder",
        "blurb": "USDT + USDC supply and exchange balances as a liquidity proxy for the next risk-on leg.",
    },
    {
        "id": "macro-calendar",
        "title": "Macro calendar",
        "blurb": "CPI, FOMC, jobs, and options-expiry overlays on the BTC chart.",
    },
    {
        "id": "whales",
        "title": "Whale alerts",
        "blurb": "Large wallet and OTC prints, plus miner-to-exchange hops.",
    },
    {
        "id": "news",
        "title": "Headline tape",
        "blurb": "A filtered news/regulatory ticker so the dashboard is not just numbers.",
    },
    {
        "id": "watchlist",
        "title": "Watchlist + alerts",
        "blurb": "Browser notifications when BTC, VIX, or a named alt cross a level you set.",
    },
    {
        "id": "portfolio",
        "title": "Local portfolio",
        "blurb": "Paste addresses or lots; keep cost basis on disk, never in a third-party cloud.",
    },
    {
        "id": "depeg",
        "title": "Depeg monitor",
        "blurb": "USDT/USDC/DAI vs $1 with an alarm when the peg slips more than a few bps.",
    },
    {
        "id": "sectors",
        "title": "Sector mosaic",
        "blurb": "L1 vs L2 vs DeFi vs AI vs meme breadth — where the bid is rotating.",
    },
)


def crypto_by_id(coin_id: str) -> CryptoSpec | None:
    for spec in CRYPTO:
        if spec.coin_id == coin_id:
            return spec
    return None


def equity_by_symbol(symbol: str) -> EquitySpec | None:
    needle = symbol.upper().lstrip("^")
    for spec in EQUITIES:
        if spec.symbol == needle or spec.yahoo.upper() == symbol.upper():
            return spec
    return None
