"""Candle data tools for market analysis."""

import asyncio
import re
from datetime import datetime as dt
from typing import Optional

from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from embient.auth import get_jwt_token
from embient.clients import basement_client


def _normalize_symbol(symbol: str) -> str:
    """Normalize symbol by removing exchange prefixes like 'X:' or 'BINANCE:'."""
    # Remove common prefixes
    prefixes = ["X:", "BINANCE:", "COINBASE:", "KRAKEN:"]
    for prefix in prefixes:
        if symbol.upper().startswith(prefix):
            symbol = symbol[len(prefix) :]
    return symbol.upper()


class LatestCandleSchema(BaseModel):
    """Arguments for get_latest_candle tool."""

    symbol: str = Field(description="Asset symbol (e.g., 'BTC/USDT')")
    exchange: str = Field(default="binance", description="Exchange name (e.g., 'binance')")


@tool(args_schema=LatestCandleSchema)
def get_latest_candle(symbol: str, exchange: str = "binance") -> str:
    """Fetches the current price (latest 5m candle) for a symbol.

    Usage:
    - Use for quick price checks before signal creation
    - Returns close price as suggestion_price for create_trading_signal
    - Faster than generate_chart when you only need current price

    Tool references:
    - Use get_candles_around_date for historical price lookup
    - Use get_indicator for technical analysis

    IMPORTANT: Requires authentication. Run 'embient login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'embient login' first.")

    symbol = _normalize_symbol(symbol)

    # Run async client method synchronously
    candle = asyncio.get_event_loop().run_until_complete(
        basement_client.get_latest_candle(token, symbol, exchange, interval="5m")
    )

    if not candle:
        raise ToolException(
            f"No candle data found for {symbol} on {exchange}. "
            "This symbol may not be available."
        )

    # Format output
    return (
        f"Latest candle for {symbol} on {exchange}:\n"
        f"- Open: {candle.get('open', 'N/A')}\n"
        f"- High: {candle.get('high', 'N/A')}\n"
        f"- Low: {candle.get('low', 'N/A')}\n"
        f"- Close: {candle.get('close', 'N/A')}\n"
        f"- Volume: {candle.get('volume', 'N/A')}\n"
        f"- Timestamp: {candle.get('timestamp', 'N/A')}"
    )


class CandlesAroundDateSchema(BaseModel):
    """Arguments for get_candles_around_date tool."""

    symbol: str = Field(description="Asset symbol (e.g., 'BTC/USDT')")
    interval: str = Field(description="Candle interval (e.g., '1h', '4h', '1d')")
    exchange: str = Field(default="binance", description="Exchange name (e.g., 'binance')")
    date: str = Field(description="Target date: 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS'")


@tool(args_schema=CandlesAroundDateSchema)
def get_candles_around_date(
    symbol: str,
    interval: str,
    date: str,
    exchange: str = "binance",
) -> str:
    """Fetches candles around a specific date for precise price lookup.

    Usage:
    - Use after visual chart analysis to get exact prices
    - Returns multiple candles around the target date
    - Use for finding support/resistance levels at specific dates

    NEVER:
    - Estimate dates - derive from chart analysis
    - Use for current price - use get_latest_candle instead

    Tool references:
    - Use get_latest_candle for current price
    - Use get_indicator for technical analysis

    IMPORTANT: Requires authentication. Run 'embient login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'embient login' first.")

    symbol = _normalize_symbol(symbol)

    # Parse the date string
    try:
        normalized_date = date.replace(" ", "T")
        if "T" in normalized_date:
            parsed_date = dt.fromisoformat(normalized_date)
        else:
            parsed_date = dt.fromisoformat(f"{normalized_date}T00:00:00")
    except ValueError as e:
        raise ToolException(
            f"Invalid date format: {date}. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS. Error: {e}"
        )

    # Get candles around the date (fetch more and filter)
    candles = asyncio.get_event_loop().run_until_complete(
        basement_client.get_candles(token, symbol, exchange, interval, limit=50)
    )

    if not candles:
        raise ToolException(
            f"No candle data found around {date} for {symbol} on {exchange}."
        )

    # Format output as a table
    output_lines = [
        f"Candles for {symbol} on {exchange} ({interval}):",
        "",
        "| Datetime            | Open      | High      | Low       | Close     | Volume     |",
        "|---------------------|-----------|-----------|-----------|-----------|------------|",
    ]

    for candle in candles[:21]:  # Limit to 21 candles
        ts = candle.get("timestamp", 0)
        if ts:
            candle_dt = dt.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")
        else:
            candle_dt = "N/A"

        output_lines.append(
            f"| {candle_dt} | {candle.get('open', 0):9.2f} | "
            f"{candle.get('high', 0):9.2f} | {candle.get('low', 0):9.2f} | "
            f"{candle.get('close', 0):9.2f} | {candle.get('volume', 0):10.2f} |"
        )

    return "\n".join(output_lines)
