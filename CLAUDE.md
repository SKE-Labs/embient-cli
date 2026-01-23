# CLAUDE.md

This file provides guidance to Claude Code when working with the embient-cli codebase.

## Project Overview

Embient CLI is an AI-powered trading assistant that runs locally while fetching market data from the Basement API (cloud). It combines the deepagents framework with trading-specific tools and a multi-agent orchestration system called "Deep Analysts".

**Key Capabilities:**
- Two modes: `code` (general coding assistant) and `trading` (Deep Analysts)
- Browser-based OAuth authentication (Claude Code-style)
- Market data tools (candles, indicators)
- Trading signal management (CRUD with HITL approval)
- Multi-agent orchestration with specialized subagents

## Development Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run embient

# Run in trading mode
uv run embient -M trading

# Authentication
uv run embient login
uv run embient logout
uv run embient status

# Run tests
uv run pytest

# Lint and format
uv run ruff check .
uv run ruff format .
```

## Architecture

### Agent Modes

The CLI supports two modes selected via `-M/--mode`:

1. **Code Mode** (default): Standard deepagents coding assistant
   - Uses `create_deep_agent` from deepagents library
   - Full middleware stack (Memory, Skills, Filesystem, Shell)
   - Human-in-the-loop for destructive operations

2. **Trading Mode**: Deep Analysts orchestrator
   - Uses `create_deep_analysts` from `embient/analysts/`
   - Supervisor delegates to specialized subagents via `task` tool
   - Session context injection (datetime, symbol, exchange, interval)

### Deep Analysts Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Supervisor (Orchestrator)                 │
│  - Routes tasks to subagents                                │
│  - Synthesizes analysis results                             │
│  - Presents findings to user                                │
├─────────────────────────────────────────────────────────────┤
│  Middleware Stack:                                          │
│  1. ToolErrorHandlingMiddleware (catches ToolException)     │
│  2. TodoListMiddleware (task tracking)                      │
│  3. MemoryMiddleware (AGENTS.md files)                      │
│  4. SkillsMiddleware (SKILL.md files)                       │
│  5. FilesystemMiddleware (file operations)                  │
│  6. SubAgentMiddleware (task tool for delegation)           │
└─────────────────────────────────────────────────────────────┘
         │              │              │
         ▼              ▼              ▼
   ┌───────────┐  ┌───────────┐  ┌───────────┐
   │ technical │  │fundamental│  │  signal   │
   │ _analyst  │  │ _analyst  │  │ _manager  │
   │           │  │           │  │           │
   │ Candles   │  │ News      │  │ Position  │
   │ Indicators│  │ Research  │  │ Signals   │
   │ Analysis  │  │           │  │ HITL      │
   └───────────┘  └───────────┘  └───────────┘
```

### Authentication Flow

1. User runs `embient login`
2. CLI opens browser to Basement API OAuth endpoint
3. User authenticates, gets redirected with auth code
4. CLI exchanges code for JWT token
5. Token stored in `~/.embient/credentials.json`
6. All API calls include JWT in Authorization header

## Key Directories

```
embient/
├── __init__.py           # Package entry point
├── main.py               # CLI entry point and argument parsing
├── agent.py              # Agent factory (create_cli_agent)
├── auth.py               # OAuth authentication (login/logout/status)
├── context.py            # Context variables (JWT, thread_id, user_profile)
├── config.py             # Settings and configuration
├── trading_config.py     # Trading-specific config (TradingConfig)
│
├── clients/
│   └── basement.py       # Basement API client (market data, signals)
│
├── trading_tools/        # Trading-specific LangChain tools
│   ├── market_data/
│   │   ├── candles.py    # get_latest_candle, get_candles_around_date
│   │   └── indicators.py # get_indicator
│   └── signals/
│       ├── trading.py    # CRUD for trading signals
│       └── position_sizing.py  # calculate_position_size
│
├── middleware/           # Custom middleware
│   ├── tool_errors.py    # ToolErrorHandlingMiddleware
│   └── subagents.py      # SubAgentMiddleware with session context
│
├── analysts/             # Deep Analysts orchestrator
│   ├── graph.py          # create_deep_analysts()
│   ├── technical.py      # Technical analyst subagent
│   ├── fundamental.py    # Fundamental analyst subagent
│   └── signal.py         # Signal manager subagent (HITL)
│
├── utils/
│   └── retry.py          # Async retry with exponential backoff
│
└── (inherited from deepagents)
    ├── skills/           # Skills system
    ├── app.py            # Textual UI application
    ├── ui.py             # Rich console helpers
    └── sessions.py       # Thread/session management
```

## Key Components

### Basement API Client (`embient/clients/basement.py`)

Async HTTP client for the Basement API at `basement.embient.ai`:

```python
from embient.clients import basement_client

# Market data
candle = await basement_client.get_latest_candle(token, "BTC/USDT", "binance")
candles = await basement_client.get_candles(token, symbol, exchange, interval, limit=100)
indicator = await basement_client.get_indicator(token, symbol, indicator, exchange, interval, params)

# Trading signals
signals = await basement_client.get_trading_signals(token, status="active", ticker="BTC/USDT")
result = await basement_client.create_trading_signal(token, **signal_data)
result = await basement_client.update_trading_signal(token, signal_id, **updates)

# User profile
profile = await basement_client.get_user_profile(token)
```

### Trading Tools (`embient/trading_tools/`)

All tools are LangChain `@tool` decorated functions with Pydantic schemas:

| Tool | Purpose |
|------|---------|
| `get_latest_candle` | Current price (5m candle) |
| `get_candles_around_date` | Historical candles around a date |
| `get_indicator` | Technical indicators (RSI, MACD, etc.) |
| `get_active_trading_signals` | List user's signals |
| `create_trading_signal` | Create new signal (requires HITL) |
| `update_trading_signal` | Update existing signal (requires HITL) |
| `calculate_position_size` | Risk-based position sizing |

### Middleware

**ToolErrorHandlingMiddleware** (`embient/middleware/tool_errors.py`):
- Catches `ToolException` from tools
- Converts to `ToolMessage` for LLM to handle gracefully
- Prevents graph crashes on tool errors

**SubAgentMiddleware** (`embient/middleware/subagents.py`):
- Provides `task` tool for subagent delegation
- Injects session context into task descriptions:
  ```markdown
  ## Session Context
  - **Current Time**: 2026-01-24 12:30:00 UTC
  - **Symbol**: BTC/USDT
  - **Exchange**: binance
  - **Interval**: 4h

  ## Task
  [Original task description]
  ```
- Retry logic for transient API errors

### Subagents (`embient/analysts/`)

| Subagent | Tools | HITL |
|----------|-------|------|
| `technical_analyst` | get_latest_candle, get_indicator, get_candles_around_date | None |
| `fundamental_analyst` | (none currently) | None |
| `signal_manager` | All signal tools + position sizing | create/update signals |

### Configuration

**Trading Config** (`embient/trading_config.py`):
```python
from embient.trading_config import get_trading_config

config = get_trading_config()
# config.default_exchange = "binance"
# config.default_interval = "4h"
# config.default_position_size = 2.0  (% of balance)
# config.max_leverage = 5.0
```

Config sources (priority order):
1. Environment variables (`EMBIENT_DEFAULT_SYMBOL`, etc.)
2. Config file (`~/.embient/trading.yaml`)
3. Defaults

## Human-in-the-Loop (HITL)

Signal creation and updates require user approval:

```python
"interrupt_on": {
    "create_trading_signal": {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_create_signal_description,
    },
}
```

When a signal tool is called:
1. Execution pauses, shows approval prompt
2. User can approve or reject
3. If rejected, LLM is informed and should NOT retry

## Environment Variables

```bash
# Required for trading mode
# (No explicit BASEMENT_API needed - defaults to basement.embient.ai)

# Optional trading defaults
EMBIENT_DEFAULT_SYMBOL=BTC/USDT
EMBIENT_DEFAULT_EXCHANGE=binance
EMBIENT_DEFAULT_INTERVAL=4h
EMBIENT_DEFAULT_POSITION_SIZE=2.0
EMBIENT_MAX_LEVERAGE=5.0

# LangSmith tracing (optional)
EMBIENT_LANGSMITH_PROJECT=embient-cli
LANGCHAIN_API_KEY=...
```

## Adding New Features

### Adding a New Trading Tool

1. Create tool in `embient/trading_tools/` with appropriate submodule
2. Use `@tool` decorator with Pydantic schema
3. Require authentication: `token = get_jwt_token(); if not token: raise ToolException(...)`
4. Export from `__init__.py`
5. Add to appropriate subagent's tools list in `embient/analysts/`

### Adding a New Subagent

1. Create file in `embient/analysts/` (e.g., `risk_analyst.py`)
2. Define prompt and `get_*_analyst(model)` function returning `SubAgent` dict
3. Add to subagents list in `embient/analysts/graph.py`
4. Update supervisor prompt with routing rules

### Adding HITL to a Tool

1. Add `interrupt_on` config to subagent definition
2. Create `_format_*_description` function for approval prompt
3. Tool will pause and show prompt before execution

## Testing

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/unit_tests/test_auth.py

# Run with coverage
uv run pytest --cov=embient
```

## Dependencies

Key dependencies (see `pyproject.toml`):
- `deepagents` - Base agent framework (local path: `../deepagents/libs/deepagents`)
- `langchain`, `langgraph` - LLM orchestration
- `httpx` - Async HTTP client for Basement API
- `tenacity` - Retry logic
- `textual` - Terminal UI
- `pyyaml` - Config file parsing

## Related Repositories

- `deepagents` - Core agent framework (parent directory)
- `park` - Cloud-based trading platform (reference implementation)
