"""Trading tools for Embient CLI.

All tools use the Basement API for data access.
"""

from embient.trading_tools.market_data import (
    get_candles_around_date,
    get_indicator,
    get_latest_candle,
)
from embient.trading_tools.signals import (
    calculate_position_size,
    create_trading_signal,
    get_active_trading_signals,
    update_trading_signal,
)

__all__ = [
    # Market Data
    "get_latest_candle",
    "get_candles_around_date",
    "get_indicator",
    # Signals
    "get_active_trading_signals",
    "create_trading_signal",
    "update_trading_signal",
    "calculate_position_size",
]
