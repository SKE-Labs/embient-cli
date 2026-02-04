"""Signal manager subagent definition."""

from deepanalysts import SubAgent
from langchain.agents.middleware.types import AgentState
from langchain.messages import ToolCall
from langchain_core.language_models import BaseChatModel
from langgraph.runtime import Runtime

from embient.trading_tools import (
    calculate_position_size,
    create_trading_signal,
    get_active_trading_signals,
    get_latest_candle,
    update_trading_signal,
)

SIGNAL_MANAGER_PROMPT = """# Signal Manager

You manage trading signals: create, update, and list.

=== SIGNAL CREATION CONSTRAINTS ===
You are STRICTLY PROHIBITED from:
- Creating signals without prior technical analysis providing entry, SL, TP, and confidence
- Skipping calculate_position_size before signal creation
- Estimating position sizes, leverage, or inventing invalid conditions
- Using price levels not derived from prior analysis

Your role requires technical analysis context to function.

## Creating a Signal

**Prerequisite**: Technical analysis MUST exist with entry conditions, stop loss, take profit levels, invalid condition, rationale, and confidence score.

**Steps:**
1. `get_latest_candle` → get current price (use as `suggestion_price`)
2. `calculate_position_size` → quantity, leverage, capital (NEVER skip)
3. `create_trading_signal` → create with ALL required parameters
4. Confirm to user

## Updating a Signal

1. `get_active_trading_signals` → find the signal
2. Verify analysis justifies the update
3. `update_trading_signal` → apply changes

## Required Signal Parameters

All fields required for creation:
- `symbol`, `position` (BUY/SELL)
- `suggestion_price` — from get_latest_candle
- `entry_conditions`, `invalid_condition` — from technical analysis
- `stop_loss`, `take_profit_levels` — from technical analysis
- `rationale`, `confidence_score` — from technical analysis
- `quantity`, `leverage`, `capital_allocated` — from calculate_position_size

## Field Quality Standards

These fields are evaluated by an automated monitoring system that checks them against live market data. Write them so a reviewer can make a clear yes/no determination.

**entry_conditions** — Specific, measurable criteria that must ALL be met. Reference timeframes, price levels or indicator thresholds, and confirmation types (candle close, breakout, retest). Supports two patterns:

Immediate (conditions can be evaluated now):
- "4H close above 75,200 resistance with RSI above 50 and volume exceeding 20-period average"
- "Price retests demand zone at 72,500-73,000 with bullish engulfing candle on 1H"

Conditional (multi-step, monitoring watches for trigger then confirmation):
- "1. Ascending triangle breaks above 82,000 resistance (4H close above). 2. Price pulls back to retest 82,000 as support. 3. Enter long on bullish 1H candle at retest with RSI above 45"
- "1. Double bottom pattern completes with neckline break above 95,200 on 4H. 2. Enter on first 1H pullback to 95,200 with bullish candle confirmation"

BAD: "buy when price comes to 75,000" / "wait for breakout" / "enter on dip"

**invalid_condition** — The structural break that kills the thesis. Must be unambiguous: specify a price level, timeframe, and what market structure it violates. This triggers automatic position exit or signal cancellation.
- "Daily close below 71,800, breaking the series of higher lows on the 4H timeframe"
- "4H close below ascending trendline support at 70,500 (4 touch points since Jan 10)"
- For conditional setups: "Ascending triangle pattern fails — price breaks below 78,500 horizontal support with 4H close"

BAD: "if price goes down too much" / "if trend changes" / "when support breaks"

**rationale** — Concise thesis (2-3 sentences) referencing: market structure, key levels with historical context, indicator confluence, and why risk is defined at the chosen stop loss.
- "4H uptrend intact with higher highs/lows since Jan 15. Price at 200-EMA confluence with horizontal support at 74,500 (3 prior bounces on Jan 20, Jan 28, Feb 2). RSI at 42 on 4H shows oversold relative to trend with room for continuation. Risk defined below demand zone at 72,500 — a daily close below invalidates the higher-low sequence."

BAD: "price looks good" / "bullish setup" / "limit buy at 75,000"

## Grounding Rules

- Create signals based STRICTLY on technical analysis provided
- Do not introduce price levels not derived from prior analysis
- Use exact price levels from technical analysis

## HITL Rejections

Some tool calls require approval. If rejected:
- Accept decision immediately — do NOT retry
- Suggest alternative or ask for clarification
- Never attempt the exact same rejected command again

> **Disclaimer**: Educational only. Not financial advice.
"""


def _format_create_signal_description(tool_call: ToolCall, _state: AgentState, _runtime: Runtime) -> str:
    """Format create_trading_signal tool call for HITL approval prompt."""
    args = tool_call.get("args", {})
    symbol = args.get("symbol", "Unknown")
    position = args.get("position", "Unknown")
    entry_price = args.get("suggestion_price", "N/A")
    stop_loss = args.get("stop_loss", "N/A")
    take_profits = args.get("take_profit_levels", [])
    confidence = args.get("confidence_score", "N/A")
    quantity = args.get("quantity", "N/A")
    leverage = args.get("leverage", "N/A")
    capital = args.get("capital_allocated", "N/A")

    tp_str = ", ".join([f"${tp}" for tp in take_profits]) if take_profits else "N/A"

    return f"""Trading Signal Creation Requires Approval

**{position} {symbol}**

Trade Details:
- Entry Price: ${entry_price}
- Stop Loss: ${stop_loss}
- Take Profit: {tp_str}
- Confidence: {confidence}%

Position Sizing:
- Quantity: {quantity}
- Leverage: {leverage}x
- Capital: ${capital}

Review carefully before approving."""


def _format_update_signal_description(tool_call: ToolCall, _state: AgentState, _runtime: Runtime) -> str:
    """Format update_trading_signal tool call for HITL approval prompt."""
    args = tool_call.get("args", {})
    signal_id = args.get("signal_id", "Unknown")
    status = args.get("status")
    entry_price = args.get("entry_price")
    exit_price = args.get("exit_price")
    profit_loss = args.get("profit_loss")
    reflection = args.get("reflection")

    updates = []
    if status:
        updates.append(f"- Status -> {status}")
    if entry_price:
        updates.append(f"- Entry Price -> ${entry_price}")
    if exit_price:
        updates.append(f"- Exit Price -> ${exit_price}")
    if profit_loss is not None:
        updates.append(f"- P/L -> ${profit_loss:+.2f}")
    if reflection:
        updates.append(f"- Reflection: {reflection[:100]}...")

    updates_str = "\n".join(updates) if updates else "No changes specified"

    return f"""Trading Signal Update Requires Approval

**Signal #{signal_id}**

Updates:
{updates_str}

Review carefully before approving."""


def get_signal_manager(model: BaseChatModel) -> SubAgent:
    """Get signal manager subagent definition."""
    return {
        "name": "signal_manager",
        "description": (
            "Trading signal manager: create, update, and list trading signals. "
            "Use ONLY after technical_analyst has provided analysis. "
            "Handles position sizing, entry/exit levels, and signal lifecycle."
        ),
        "system_prompt": SIGNAL_MANAGER_PROMPT,
        "tools": [
            get_active_trading_signals,
            calculate_position_size,
            create_trading_signal,
            update_trading_signal,
            get_latest_candle,
        ],
        "model": model,
        "interrupt_on": {
            "create_trading_signal": {
                "allowed_decisions": ["approve", "reject"],
                "description": _format_create_signal_description,
            },
            "update_trading_signal": {
                "allowed_decisions": ["approve", "reject"],
                "description": _format_update_signal_description,
            },
        },
    }
