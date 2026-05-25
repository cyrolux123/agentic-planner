"""
Knowledge Lookup Tool — Wikipedia REST API (free, no key required).

Custom tool choice rationale: Wikipedia provides authoritative, structured
factual knowledge that complements web search (which returns opinionated
snippets from arbitrary sources).  This creates a clean separation of
concerns: knowledge_lookup for facts/definitions, web_search for current events.

Two-stage fetch:
  1. Direct REST summary endpoint  (fast, clean extract)
  2. Full-text search fallback     (handles misspellings / ambiguous terms)

Timeout: 10 s per HTTP request, 25 s total wall clock via daemon thread.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

import requests

from .base import Tool


WIKI_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"
WIKI_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
HTTP_TIMEOUT: int = 10        # per-request
THREAD_TIMEOUT: int = 25      # wall-clock cap
HEADERS = {"User-Agent": "AgenticPlanner/1.0 (educational project)"}
MAX_EXTRACT_CHARS: int = 2_000


class KnowledgeLookupTool(Tool):
    name = "knowledge_lookup"
    description = (
        "Look up factual knowledge from Wikipedia. "
        "Best for: definitions, scientific concepts, historical events, "
        "biographies, geography. Returns a concise, authoritative summary."
    )
    input_schema = {
        "topic": "string — the topic, concept, or entity to look up",
    }

    def run(self, topic: str = "", **_kwargs) -> str:  # type: ignore[override]
        topic = (topic or "").strip()
        if not topic:
            return "Error: 'topic' parameter is required and cannot be empty."

        container: Dict[str, Any] = {"result": None, "error": None}

        def _fetch() -> None:
            try:
                container["result"] = self._fetch_summary(topic)
            except requests.RequestException as exc:
                container["error"] = f"Network error: {exc}"
            except Exception as exc:
                container["error"] = f"Unexpected error: {exc}"

        thread = threading.Thread(target=_fetch, daemon=True)
        thread.start()
        thread.join(timeout=THREAD_TIMEOUT)

        if thread.is_alive():
            return (
                f"Error: Knowledge lookup timed out after {THREAD_TIMEOUT}s "
                f"for topic: '{topic}'."
            )
        if container["error"]:
            return f"Error: {container['error']}"
        return container["result"] or f"No information found for: '{topic}'"

   
    # Internal helpers
    def _fetch_summary(self, topic: str) -> str:
        """Try direct slug lookup, then fall back to search API."""
        slug = topic.replace(" ", "_")
        resp = requests.get(
            WIKI_SUMMARY_URL.format(slug),
            timeout=HTTP_TIMEOUT,
            headers=HEADERS,
        )

        if resp.status_code == 200:
            return self._format(resp.json())

        if resp.status_code not in (404, 301):
            # Unexpected server error — surface it
            return (
                f"Error: Wikipedia returned HTTP {resp.status_code} "
                f"for slug '{slug}'."
            )

        # fallback: full-text search 
        search_resp = requests.get(
            WIKI_SEARCH_URL,
            params={
                "action": "query",
                "list": "search",
                "srsearch": topic,
                "format": "json",
                "srlimit": 1,
            },
            timeout=HTTP_TIMEOUT,
            headers=HEADERS,
        )
        search_resp.raise_for_status()
        hits = search_resp.json().get("query", {}).get("search", [])

        if not hits:
            return f"No Wikipedia article found for: '{topic}'"

        best_title: str = hits[0]["title"]
        slug2 = best_title.replace(" ", "_")
        resp2 = requests.get(
            WIKI_SUMMARY_URL.format(slug2),
            timeout=HTTP_TIMEOUT,
            headers=HEADERS,
        )
        if resp2.status_code == 200:
            return self._format(resp2.json())

        return f"Could not retrieve Wikipedia article for: '{topic}'"

    @staticmethod
    def _format(data: dict) -> str:
        title: str = data.get("title", "Unknown")
        extract: str = data.get("extract", "No summary available.")
        description: str = data.get("description", "")

        parts = [f"## {title}"]
        if description:
            parts.append(f"*{description}*")
        parts.append(extract[:MAX_EXTRACT_CHARS])
        if len(extract) > MAX_EXTRACT_CHARS:
            parts.append("*(summary truncated)*")

        return "\n\n".join(parts)
