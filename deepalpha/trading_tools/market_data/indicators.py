"""Technical indicator tools for market analysis."""

from datetime import datetime as dt

from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from deepalpha.clients import basement_client
from deepalpha.context import get_jwt_token

MAX_INDICATOR_HISTORY = 200


def _flatten(obj, prefix=""):
    """Flatten nested dicts to (key, value) pairs."""
    if not isinstance(obj, dict):
        return [(prefix, obj)] if prefix else [("value", obj)]
    items = []
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.extend(_flatten(v, key))
        else:
            items.append((key, v))
    return items


def _fmt_cell(val):
    if val is None:
        return "N/A"
    if isinstance(val, float):
        return f"{val:.10g}"
    return str(val)


def _format_history_table(
    rows: list[dict], indicator: str, symbol: str, interval: str
) -> str:
    """Render indicator history (newest-first input) as a markdown table.

    Columns are derived from the first row's flattened ``value`` dict; rows that
    happen to omit a key render as ``N/A``.
    """
    rows = list(reversed(rows))  # oldest-first for display
    flats = [dict(_flatten(r.get("value", {}))) for r in rows]

    # Union of all flattened keys, first-seen order — guards against
    # heterogeneous rows (e.g. an indicator schema change mid-history).
    cols: list[str] = []
    seen: set[str] = set()
    for f in flats:
        for k in f:
            if k not in seen:
                seen.add(k)
                cols.append(k)

    title = f"Last {len(rows)} {indicator.upper()} value(s) for {symbol} ({interval}):"
    header_cells = ["Datetime", "Unix Timestamp", *cols]
    header = "| " + " | ".join(header_cells) + " |"
    sep = "|" + "|".join("---" for _ in header_cells) + "|"

    lines = [title, "", header, sep]
    for r, flat in zip(rows, flats, strict=True):
        ts = r.get("timestamp")
        ts_str = (
            dt.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")
            if isinstance(ts, (int, float))
            else "N/A"
        )
        cells = [ts_str, str(ts) if ts is not None else "N/A"] + [
            _fmt_cell(flat.get(c)) for c in cols
        ]
        lines.append("| " + " | ".join(cells) + " |")

    params = rows[-1].get("parameters") or {}
    if params:
        params_str = ", ".join(f"{k}={v}" for k, v in params.items())
        lines.append("")
        lines.append(f"Params: {params_str}")

    return "\n".join(lines)


def _format_single(
    data: dict, indicator: str, symbol: str, interval: str, period: int | None
) -> str:
    """Per-indicator pretty-printed single value (parity with prior behavior)."""
    indicator_lower = indicator.lower()

    if indicator_lower == "rsi":
        value = data.get("value", data.get("rsi", "N/A"))
        return f"RSI ({interval}) for {symbol}: {value}"

    if indicator_lower == "macd":
        macd = data.get("macd", data.get("value", "N/A"))
        signal = data.get("signal", data.get("macd_signal", "N/A"))
        histogram = data.get("histogram", data.get("macd_histogram", "N/A"))
        return (
            f"MACD ({interval}) for {symbol}:\n- MACD Line: {macd}\n- Signal Line: {signal}\n- Histogram: {histogram}"
        )

    if indicator_lower in ("ema", "sma"):
        value = data.get("value", "N/A")
        p = period or 20
        return f"{indicator.upper()}({p}) ({interval}) for {symbol}: {value}"

    if indicator_lower == "bbands":
        upper = data.get("upper", data.get("valueUpperBand", "N/A"))
        middle = data.get("middle", data.get("valueMiddleBand", "N/A"))
        lower = data.get("lower", data.get("valueLowerBand", "N/A"))
        return f"Bollinger Bands ({interval}) for {symbol}:\n- Upper: {upper}\n- Middle: {middle}\n- Lower: {lower}"

    if indicator_lower == "stoch":
        k = data.get("k", data.get("value_k", "N/A"))
        d = data.get("d", data.get("value_d", "N/A"))
        return f"Stochastic ({interval}) for {symbol}:\n- %K: {k}\n- %D: {d}"

    if indicator_lower == "dmi":
        plus_di = data.get("plus_di", data.get("adx_plus_di", "N/A"))
        minus_di = data.get("minus_di", data.get("adx_minus_di", "N/A"))
        adx = data.get("adx", "N/A")
        return f"DMI ({interval}) for {symbol}:\n- +DI: {plus_di}\n- -DI: {minus_di}\n- ADX: {adx}"

    if indicator_lower == "supertrend":
        value = data.get("value", data.get("supertrend", "N/A"))
        direction = data.get("direction", data.get("supertrend_direction", "N/A"))
        return f"Supertrend ({interval}) for {symbol}:\n- Value: {value}\n- Direction: {direction}"

    return f"{indicator.upper()} ({interval}) for {symbol}: {data}"


class IndicatorsSchema(BaseModel):
    """Arguments for get_indicators tool."""

    symbol: str = Field(description="Asset symbol (e.g., 'BTC/USDT')")
    indicator: str = Field(description="Indicator name: rsi, macd, ema, sma, bbands, stoch, mfi, dmi, supertrend")
    exchange: str = Field(default="binance", description="Exchange name")
    interval: str = Field(default="4h", description="Candle interval (e.g., '1h', '4h', '1d')")
    count: int = Field(
        default=1,
        ge=1,
        le=MAX_INDICATOR_HISTORY,
        description="Number of most-recent indicator values to return (1 = latest only). Use 1 for a quick reading; bump to e.g. 5-20 for slope, divergence, or squeeze checks.",
    )
    period: int | None = Field(default=None, description="Indicator period (e.g., 14 for RSI)")


@tool(args_schema=IndicatorsSchema)
async def get_indicators(
    symbol: str,
    indicator: str,
    exchange: str = "binance",
    interval: str = "4h",
    count: int = 1,
    period: int | None = None,
) -> str:
    """Fetches the last N values for a technical indicator.

    With count=1 (default) returns the single latest value pretty-printed —
    suitable for confirming a chart read. With count>1 returns a markdown table
    of the most recent N values (oldest first), useful for slope, divergence,
    and squeeze analysis.

    Indicator categories:
    - Momentum: rsi, stoch, mfi
    - Trend: ema, sma, macd, supertrend, dmi
    - Volatility: bbands (Bollinger Bands)

    Common periods:
    - RSI: 14 (default)
    - EMA/SMA: 20, 50, 200
    - MACD: 12/26/9 (default)
    - Bollinger Bands: 20 (default)

    Usage:
    - Use for confirming chart analysis with numerical data
    - Combine multiple indicators for confluence
    - Check divergences between price and momentum

    Tool references:
    - Use get_latest_candle for current price
    - Use get_candles_around_date for historical data

    IMPORTANT: Requires authentication. Run 'deepalpha login' first.
    """
    token = get_jwt_token()
    if not token:
        raise ToolException("Not authenticated. Please run 'deepalpha login' first.")

    # Normalize symbol
    prefixes = ["BINANCE:", "COINBASE:"]
    for prefix in prefixes:
        if symbol.upper().startswith(prefix):
            symbol = symbol[len(prefix) :]
    symbol = symbol.upper()

    params = {}
    if period:
        params["period"] = period

    # Get indicator data
    try:
        rows = await basement_client.get_indicators(
            token, symbol, indicator, exchange, interval, count, params
        )

        if not rows:
            raise ToolException(
                f"No {indicator} data found for {symbol} on {exchange}. "
                f"The indicator may not be available for this symbol."
            )
    except ToolException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "403" in error_msg:
            raise ToolException("Authentication failed. Run 'deepalpha login' to re-authenticate.") from e
        elif "404" in error_msg:
            raise ToolException(
                f"No {indicator} data found for {symbol} on {exchange}. The indicator may not be calculated yet."
            ) from e
        elif "timeout" in error_msg.lower():
            raise ToolException(f"Request timeout while fetching {indicator} for {symbol}.") from e
        else:
            raise ToolException(f"Failed to fetch {indicator} for {symbol}: {error_msg}") from e

    if count == 1:
        return _format_single(rows[0], indicator, symbol, interval, period)
    return _format_history_table(rows, indicator, symbol, interval)
