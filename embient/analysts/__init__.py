"""Analyst subagent definitions for Deep Analysts workflow."""

from embient.analysts.fundamental import get_fundamental_analyst
from embient.analysts.graph import create_deep_analysts
from embient.analysts.technical import get_technical_analyst

__all__ = [
    "create_deep_analysts",
    "get_fundamental_analyst",
    "get_technical_analyst",
]
