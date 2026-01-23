"""Trading-specific configuration for Embient CLI."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from embient.config import settings


@dataclass
class TradingConfig:
    """Trading mode configuration.

    Configuration is loaded from (in priority order):
    1. Environment variables (EMBIENT_DEFAULT_SYMBOL, etc.)
    2. Config file (~/.embient/trading.yaml)
    3. Defaults

    Attributes:
        default_symbol: Default trading symbol (e.g., "BTC/USDT")
        default_exchange: Default exchange (default: "binance")
        default_interval: Default timeframe (default: "4h")
        default_position_size: Default position size as % of balance (default: 2.0)
        max_leverage: Maximum leverage allowed (default: 5.0)
    """

    default_symbol: str | None = None
    default_exchange: str = "binance"
    default_interval: str = "4h"
    default_position_size: float = 2.0
    max_leverage: float = 5.0

    @classmethod
    def load(cls) -> "TradingConfig":
        """Load trading configuration from environment and config file.

        Returns:
            TradingConfig instance with merged configuration.
        """
        # Start with defaults
        config_dict: dict = {}

        # Load from config file if exists
        config_file = settings.user_embient_dir / "trading.yaml"
        if config_file.exists():
            try:
                with open(config_file) as f:
                    file_config = yaml.safe_load(f) or {}
                    config_dict.update(file_config)
            except (yaml.YAMLError, OSError):
                pass  # Use defaults if file is invalid

        # Override with environment variables
        if os.environ.get("EMBIENT_DEFAULT_SYMBOL"):
            config_dict["default_symbol"] = os.environ["EMBIENT_DEFAULT_SYMBOL"]
        if os.environ.get("EMBIENT_DEFAULT_EXCHANGE"):
            config_dict["default_exchange"] = os.environ["EMBIENT_DEFAULT_EXCHANGE"]
        if os.environ.get("EMBIENT_DEFAULT_INTERVAL"):
            config_dict["default_interval"] = os.environ["EMBIENT_DEFAULT_INTERVAL"]
        if os.environ.get("EMBIENT_DEFAULT_POSITION_SIZE"):
            try:
                config_dict["default_position_size"] = float(
                    os.environ["EMBIENT_DEFAULT_POSITION_SIZE"]
                )
            except ValueError:
                pass
        if os.environ.get("EMBIENT_MAX_LEVERAGE"):
            try:
                config_dict["max_leverage"] = float(os.environ["EMBIENT_MAX_LEVERAGE"])
            except ValueError:
                pass

        return cls(**config_dict)

    def save(self, config_file: Path | None = None) -> None:
        """Save trading configuration to file.

        Args:
            config_file: Path to config file. Defaults to ~/.embient/trading.yaml
        """
        if config_file is None:
            config_file = settings.user_embient_dir / "trading.yaml"

        # Ensure directory exists
        config_file.parent.mkdir(parents=True, exist_ok=True)

        config_dict = {
            "default_exchange": self.default_exchange,
            "default_interval": self.default_interval,
            "default_position_size": self.default_position_size,
            "max_leverage": self.max_leverage,
        }

        # Only include symbol if set
        if self.default_symbol:
            config_dict["default_symbol"] = self.default_symbol

        with open(config_file, "w") as f:
            yaml.dump(config_dict, f, default_flow_style=False)


# Global instance (lazy loaded)
_trading_config: TradingConfig | None = None


def get_trading_config() -> TradingConfig:
    """Get the trading configuration instance.

    Returns:
        TradingConfig instance (loaded once and cached).
    """
    global _trading_config
    if _trading_config is None:
        _trading_config = TradingConfig.load()
    return _trading_config


def reload_trading_config() -> TradingConfig:
    """Reload trading configuration from file and environment.

    Returns:
        Fresh TradingConfig instance.
    """
    global _trading_config
    _trading_config = TradingConfig.load()
    return _trading_config
