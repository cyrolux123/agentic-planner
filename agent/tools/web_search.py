"""
Web Search Tool — DuckDuckGo (free, no API key required).

Uses a daemon thread + join(timeout) pattern instead of SIGALRM so the
timeout works on both Linux and Windows.  No bare except: pass blocks.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from ddgs import DDGS

from .base import Tool


TOOL_TIMEOUT: int = 15   # seconds before the search thread is abandoned
MAX_RESULTS: int = 4


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web for current information. "
        "Returns up to 4 results with title, snippet, and URL. "
        "Best for recent events, factual lookups, and web content."
    )
    input_schema = {
        "query": "string — the search query (be specific for better results)",
    }

    def run(self, query: str = "", **_kwargs) -> str:  # type: ignore[override]
        query = (query or "").strip()
        if not query:
            return "Error: 'query' parameter is required and cannot be empty."

        container: Dict[str, Any] = {"results": None, "error": None}

        def _search() -> None:
            try:
                with DDGS() as ddgs:
                    container["results"] = list(
                        ddgs.text(query, max_results=MAX_RESULTS)
                    )
            except Exception as exc:  # network errors, rate limits, etc.
                container["error"] = str(exc)

        thread = threading.Thread(target=_search, daemon=True)
        thread.start()
        thread.join(timeout=TOOL_TIMEOUT)

        if thread.is_alive():
            return (
                f"Error: Web search timed out after {TOOL_TIMEOUT}s "
                f"for query: '{query}'. "
                "Try a shorter, more specific query."
            )

        if container["error"]:
            return f"Error: Web search failed — {container['error']}"

        results: Optional[list] = container["results"]
        if not results:
            return (
                f"No results found for query: '{query}'. "
                "Try rephrasing or use knowledge_lookup instead."
            )

        lines = [f"Search results for: \"{query}\"\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            body = r.get("body", "No snippet")[:300]
            href = r.get("href", "")
            lines.append(f"{i}. {title}\n   {body}\n   URL: {href}")

        return "\n\n".join(lines)
