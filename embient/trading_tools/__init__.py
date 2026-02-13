"""Trading tools for Embient CLI.

All tools use the Basement API for data access.
"""

from embient.trading_tools.market_data import (
    generate_chart,
    get_candles_around_date,
    get_indicator,
    get_latest_candle,
)
from embient.trading_tools.memory import (
    create_memory,
    delete_memory,
    list_memories,
    update_memory,
)
from embient.trading_tools.research import (
    get_economics_calendar,
    get_financial_news,
    get_fundamentals,
    web_search,
)
from embient.trading_tools.signals import (
    calculate_position_size,
    create_trading_signal,
    get_active_trading_signals,
    update_trading_signal,
)

__all__ = [
    # Market Data
    "generate_chart",
    "get_latest_candle",
    "get_candles_around_date",
    "get_indicator",
    # Research
    "web_search",
    "get_financial_news",
    "get_fundamentals",
    "get_economics_calendar",
    # Signals
    "get_active_trading_signals",
    "create_trading_signal",
    "update_trading_signal",
    "calculate_position_size",
    # Memory
    "list_memories",
    "create_memory",
    "update_memory",
    "delete_memory",
]
