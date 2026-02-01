# CLAUDE.md

This file provides guidance to Claude Code when working with the embient-cli codebase.

## Project Overview

Embient CLI is an AI-powered trading assistant that runs locally while fetching market data from the Basement API (cloud). It uses the Deep Analysts multi-agent orchestration system with specialized subagents for technical analysis, fundamental research, and signal management.

**Key Capabilities:**
- Deep Analysts orchestrator with supervisor + specialized subagents
- BYOK model support (OpenAI, Anthropic, Google Gemini)
- Browser-based OAuth authentication
- Market data tools (candles, indicators)
- Trading signal management (CRUD with HITL approval)
- Remote sandbox execution (Modal, Daytona, RunLoop)
- Persistent sessions with SQLite checkpointing
- Skills system for custom workflows
- Textual-based terminal UI

## Development Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run embient

# Authentication
uv run embient login
uv run embient logout
uv run embient status

# Run tests
uv run pytest
make test                    # Unit tests (with --disable-socket)
make integration_tests       # Integration tests
make test_watch              # Tests in watch mode
make coverage                # Tests with coverage report

# Lint and format
uv run ruff check .
uv run ruff format .
make lint                    # Lint check + format diff
make format                  # Auto-fix formatting and lint
make check_imports           # Verify import structure
```

### CLI Usage

```bash
# Interactive mode (default)
uv run embient

# With specific model (auto-detects provider from name)
uv run embient --model gpt-5-mini
uv run embient --model claude-sonnet-4-5-20250929
uv run embient --model gemini-3-flash-preview

# Resume previous session
uv run embient -r              # Most recent thread
uv run embient -r <thread_id>  # Specific thread

# Auto-submit initial prompt
uv run embient -m "Analyze BTC/USDT"

# Remote sandbox execution
uv run embient --sandbox modal
uv run embient --sandbox daytona --sandbox-id <id>
uv run embient --sandbox runloop --sandbox-setup setup.sh

# Skip HITL approval prompts
uv run embient --auto-approve

# Agent management
uv run embient list                              # List agents
uv run embient reset --agent myagent             # Reset to default
uv run embient reset --agent new --target old    # Copy from another

# Thread management
uv run embient threads list
uv run embient threads list --agent myagent --limit 10
uv run embient threads delete <thread_id>

# Skills management
uv run embient skills
```

## Architecture

### Agent Architecture

`create_cli_agent` (in `embient/agent.py`) is the main entry point. It internally uses `create_deep_analysts` to build a supervisor agent with specialized subagents. All interactive sessions use the Deep Analysts orchestrator.

### Deep Analysts Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Supervisor (Orchestrator)                 │
│  - Routes tasks to subagents via `task` tool                │
│  - Synthesizes analysis results                             │
│  - Presents findings to user                                │
├─────────────────────────────────────────────────────────────┤
│  Orchestrator Middleware Stack:                              │
│  1. ToolErrorHandlingMiddleware (catches ToolException)      │
│  2. TodoListMiddleware (task tracking)                       │
│  3. MemoryMiddleware (AGENTS.md files, if configured)        │
│  4. SkillsMiddleware (skills dirs, if configured)            │
│  5. FilesystemMiddleware (file operations)                   │
│  6. SubAgentMiddleware (task tool for delegation)            │
│  7. PatchToolCallsMiddleware (dangling tool calls)           │
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

Per-subagent middleware:
  ToolErrorHandling → Skills* → Filesystem → PatchToolCalls
```

### Authentication Flow

1. User runs `embient login`
2. CLI opens browser to Basement API OAuth endpoint
3. User authenticates, gets redirected with auth code
4. CLI exchanges code for JWT token
5. Token stored in `~/.embient/credentials.json`
6. All API calls include JWT in Authorization header

### Model Support (BYOK)

Provider is auto-detected from model name. Priority when no `--model` flag:
1. `OPENAI_API_KEY` → OpenAI (default: `gpt-5-mini`)
2. `ANTHROPIC_API_KEY` → Anthropic (default: `claude-sonnet-4-5-20250929`)
3. `GOOGLE_API_KEY` → Google (default: `gemini-3-flash-preview`)

Override with env vars: `OPENAI_MODEL`, `ANTHROPIC_MODEL`, `GOOGLE_MODEL`.

## Key Directories

```
embient/
├── __init__.py              # Package entry point (exports cli_main)
├── __main__.py              # Python -m entry point
├── _version.py              # Version info
├── main.py                  # CLI entry point and argument parsing
├── agent.py                 # Agent factory (create_cli_agent → create_deep_analysts)
├── auth.py                  # OAuth authentication (login/logout/status)
├── context.py               # Context variables (auth token, thread_id, user_profile, images)
├── config.py                # Settings, model creation, color scheme, commands
├── trading_config.py        # Trading-specific config (TradingConfig dataclass)
├── tools.py                 # General tools (http_request, fetch_url, web_search)
├── shell.py                 # Shell execution
├── file_ops.py              # File operations utilities
├── skills.py                # Skills system entry point
├── sessions.py              # Thread/session management (SQLite checkpointer)
├── app.py                   # Textual UI application
├── app.tcss                 # Textual CSS styles
├── ui.py                    # Rich console helpers
├── textual_adapter.py       # Textual UI adapter
├── image_utils.py           # Image processing
├── clipboard.py             # Clipboard management
├── input.py                 # Input handling
├── local_context.py         # Local execution context
├── project_utils.py         # Project utilities
├── default_agent_prompt.md  # Default system prompt template
│
├── analysts/                # Deep Analysts orchestrator
│   ├── graph.py             # create_deep_analysts() with middleware stack
│   ├── technical.py         # Technical analyst subagent
│   ├── fundamental.py       # Fundamental analyst subagent
│   └── signal.py            # Signal manager subagent (HITL)
│
├── clients/
│   ├── basement.py          # Basement API client (market data, signals, economics calendar)
│   └── park.py              # Park API client (web search, financial news, fundamentals)
│
├── trading_tools/           # Trading-specific LangChain tools
│   ├── market_data/
│   │   ├── candles.py       # get_latest_candle, get_candles_around_date
│   │   └── indicators.py    # get_indicator
│   ├── research/            # Research tools (via Park + Basement APIs)
│   │   ├── web_search.py    # web_search (Park: POST /api/v1/search)
│   │   ├── news.py          # get_financial_news (Park: POST /api/v1/search/news)
│   │   ├── fundamentals.py  # get_fundamentals (Park: GET /api/v1/fundamentals/{ticker})
│   │   └── economics.py     # get_economics_calendar (Basement: GET /api/v1/economics-calendar)
│   └── signals/
│       ├── trading.py       # CRUD for trading signals
│       └── position_sizing.py  # calculate_position_size
│
├── integrations/            # Remote sandbox integrations
│   ├── sandbox_factory.py   # Factory for creating sandboxes
│   ├── modal.py             # Modal sandbox backend
│   ├── daytona.py           # Daytona sandbox backend
│   └── runloop.py           # RunLoop sandbox backend
│
├── skills/                  # Skills system
│   ├── load.py              # Load skills from files
│   └── commands.py          # Skills CLI commands
│
├── widgets/                 # Textual UI components
│   ├── approval.py          # HITL approval menu
│   ├── autocomplete.py      # Chat input autocomplete
│   ├── chat_input.py        # Chat input widget
│   ├── diff.py              # Diff viewer
│   ├── history.py           # Chat history
│   ├── loading.py           # Loading spinner
│   ├── messages.py          # Message renderers (User, Assistant, Tool, Error, System)
│   ├── status.py            # Status bar
│   ├── tool_renderers.py    # Tool output rendering
│   ├── tool_widgets.py      # Tool call widgets
│   └── welcome.py           # Welcome banner
│
└── utils/
    └── retry.py             # Async retry with exponential backoff

libs/
└── deepanalysts/            # Middleware & backend library (published to PyPI)
    └── deepanalysts/
        ├── middleware/       # All middleware implementations
        │   ├── tool_errors.py       # ToolErrorHandlingMiddleware
        │   ├── memory.py            # MemoryMiddleware (AGENTS.md)
        │   ├── filesystem.py        # FilesystemMiddleware
        │   ├── skills.py            # SkillsMiddleware
        │   ├── subagents.py         # SubAgentMiddleware (task tool)
        │   ├── summarization.py     # SummarizationMiddleware
        │   └── patch_tool_calls.py  # PatchToolCallsMiddleware
        ├── backends/         # Storage & execution backends
        │   ├── filesystem.py        # FilesystemBackend, LocalFilesystemBackend
        │   ├── composite.py         # CompositeBackend (routing)
        │   ├── sandbox.py           # RestrictedSubprocessBackend
        │   ├── store.py             # StoreBackend
        │   └── basement.py          # BasementMemoryLoader, BasementSkillsLoader
        └── clients/
            └── basement.py          # Basement API client

examples/
└── skills/                  # Example skill workflows
    ├── skill-creator/
    ├── web-research/
    ├── langgraph-docs/
    └── arxiv-search/

tests/
├── unit_tests/              # Unit tests (pytest --disable-socket)
└── integration_tests/       # Integration tests (sandbox operations)
```

## Key Components

### Basement API Client (`embient/clients/basement.py`)

Async HTTP client for the Basement API. Base URL from `BASEMENT_API` env var (default: `https://basement.embient.ai`):

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

# User profile & portfolio
profile = await basement_client.get_user_profile(token)
portfolio = await basement_client.get_portfolio_summary(token)

# Favorite tickers & stats
favorites = await basement_client.get_favorite_tickers(token)
stats = await basement_client.get_ticker_stats(token, "X:BTC/USDT")

# Economics calendar
events = await basement_client.get_economics_calendar(token, from_date="2025-07-01", to_date="2025-07-07", impact="High")
```

### Park API Client (`embient/clients/park.py`)

Async HTTP client for the Park API. Base URL from `PARK_API` env var (default: `https://park.embient.ai`). Used by research tools to access web search, financial news, and stock fundamentals:

```python
from embient.clients import park_client

results = await park_client.web_search(token, "AAPL earnings")
news = await park_client.get_financial_news(token, "Bitcoin", time_range="week")
data = await park_client.get_fundamentals(token, "AAPL", data_type="overview")
```

### Tools

**General Tools** (`embient/tools.py`):

| Tool | Purpose |
|------|---------|
| `http_request` | Make HTTP requests to APIs (GET, POST, etc.) |
| `fetch_url` | Fetch URL and convert HTML to markdown |

**Trading Tools** (`embient/trading_tools/`):

All tools are LangChain `@tool` decorated functions with Pydantic schemas:

| Tool | Source | Purpose |
|------|--------|---------|
| `get_latest_candle` | Basement | Current price (5m candle) |
| `get_candles_around_date` | Basement | Historical candles around a date |
| `get_indicator` | Basement | Technical indicators (RSI, MACD, etc.) |
| `web_search` | Park | General web search (replaces Tavily) |
| `get_financial_news` | Park | Financial news from trusted sources |
| `get_fundamentals` | Park | Stock fundamentals via yfinance (P/E, financials, etc.) |
| `get_economics_calendar` | Basement | Economic calendar events (NFP, CPI, etc.) |
| `get_active_trading_signals` | Basement | List user's signals |
| `create_trading_signal` | Basement | Create new signal (requires HITL) |
| `update_trading_signal` | Basement | Update existing signal (requires HITL) |
| `calculate_position_size` | Local | Risk-based position sizing |

### Middleware

All middleware classes live in `libs/deepanalysts/deepanalysts/middleware/`:

**ToolErrorHandlingMiddleware** (`middleware/tool_errors.py`):
- Catches `ToolException` from tools
- Converts to `ToolMessage` for LLM to handle gracefully
- Prevents graph crashes on tool errors

**SubAgentMiddleware** (`middleware/subagents.py`):
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

**PatchToolCallsMiddleware** (`middleware/patch_tool_calls.py`):
- Handles dangling tool calls from graph interruptions (e.g., HITL)
- Always placed last in the middleware stack

**Other middleware:** MemoryMiddleware (AGENTS.md), SkillsMiddleware, FilesystemMiddleware, SummarizationMiddleware, TodoListMiddleware (from `langchain.agents.middleware`).

### Subagents (`embient/analysts/`)

| Subagent | Tools | HITL |
|----------|-------|------|
| `technical_analyst` | get_latest_candle, get_indicator, get_candles_around_date | None |
| `fundamental_analyst` | get_financial_news, get_fundamentals, get_economics_calendar | None |
| `signal_manager` | All signal tools + position sizing + get_latest_candle | create/update signals |

### Context Variables (`embient/context.py`)

Session-scoped context using `contextvars`:

| Variable | Purpose |
|----------|---------|
| `auth_token` | CLI session token for API calls (aliases: `jwt_token`) |
| `thread_id` | Conversation thread ID |
| `user_profile` | Account balance, risk settings |
| `entry_plan_images` | Images for trading signal entry plans |
| `invalid_condition_images` | Images for signal invalidation conditions |
| `screenshots` | HITL-captured chart screenshots |

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

### Sandbox Integrations (`embient/integrations/`)

Remote code execution via `--sandbox` flag:

| Provider | Flag | Backend |
|----------|------|---------|
| Local (default) | `--sandbox none` | `FilesystemBackend` (with local `execute()` support) |
| Modal | `--sandbox modal` | `ModalBackend` |
| Daytona | `--sandbox daytona` | `DaytonaBackend` |
| RunLoop | `--sandbox runloop` | `RunLoopBackend` |

Options: `--sandbox-id <id>` (reuse existing), `--sandbox-setup <script>` (init script).

### Interactive Commands

During a session, these slash commands are available:
- `/clear` — Clear screen and reset conversation
- `/help` — Show help
- `/remember` — Review conversation and update memory/skills
- `/tokens` — Show token usage
- `/quit` or `/exit` — Exit

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
1. Execution pauses, shows approval prompt via `widgets/approval.py`
2. User can approve or reject
3. If rejected, LLM is informed and should NOT retry

Use `--auto-approve` to skip all HITL prompts.

## Environment Variables

```bash
# LLM API keys (BYOK — at least one required)
OPENAI_API_KEY=sk-...          # OpenAI
ANTHROPIC_API_KEY=sk-ant-...   # Anthropic
GOOGLE_API_KEY=AIza...         # Google Gemini

# Model overrides (optional, auto-detected from API key priority)
OPENAI_MODEL=gpt-5-mini
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929
GOOGLE_MODEL=gemini-3-flash-preview

# API base URLs (optional, defaults to production)
BASEMENT_API=https://basement.embient.ai
PARK_API=https://park.embient.ai

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

### Adding a New General Tool

1. Add function to `embient/tools.py`
2. Add to the `tools` list in `run_textual_cli_async` (`embient/main.py`)

## Testing

```bash
# Run all tests
uv run pytest
make test

# Run specific test file
uv run pytest tests/unit_tests/test_agent.py

# Run with coverage
make coverage

# Integration tests (sandbox operations)
make integration_tests

# Watch mode
make test_watch
```

## Dependencies

Key dependencies (see `pyproject.toml`):
- `deepanalysts>=0.1.0` — Middleware & backend library (published to PyPI; local dev path in `libs/deepanalysts`)
- `langchain>=1.2.3`, `langchain-openai`, `langchain-google-genai` — LLM orchestration
- `langgraph-checkpoint-sqlite` — Session persistence
- `httpx>=0.28.0` — Async HTTP client for Basement API
- `tenacity>=8.2.0` — Retry logic
- `textual>=1.0.0`, `textual-autocomplete>=3.0.0` — Terminal UI
- `rich>=13.0.0` — CLI formatting
- `requests` — Sync HTTP client (tools)
- `markdownify>=0.13.0` — HTML to markdown
- `pillow>=10.0.0` — Image processing
- `pyyaml>=6.0` — Config file parsing
- `aiosqlite>=0.19.0` — Async SQLite for sessions
- `daytona>=0.113.0`, `modal>=0.65.0`, `runloop-api-client>=0.69.0` — Sandbox providers
- `python-dotenv` — Environment variable loading
- `prompt-toolkit>=3.0.52` — Terminal input handling

## Related Repositories

- `park` — Cloud-based trading platform (reference implementation)
