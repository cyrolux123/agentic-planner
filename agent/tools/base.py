"""Abstract base class for all agent tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict


class Tool(ABC):
    """Every tool must declare a name, description, and input schema.

    The input_schema dict is injected verbatim into the system prompt so the
    LLM knows exactly what JSON keys to supply.
    """

    name: str
    description: str
    input_schema: Dict[str, str]  # {"param_name": "type - description"}

    @abstractmethod
    def run(self, **kwargs) -> str:
        """Execute the tool and return a plain-text observation.

        On error, return a string starting with "Error:" — the agent
        treats this as a failed observation and may replan.
        Never raise; surface errors as return values.
        """
