"""
Reflection & Replanning Engine — final submission version.

Detects two failure patterns after every tool call:
  1. Consecutive failures  — 3 identical-tool failures in a row.
  2. Loop detection:
       A. Exact fingerprint  — identical action+input repeated in window.
       B. Semantic similarity — Jaccard token overlap >= 0.65 on same-tool
          calls within the recent LOOP_WINDOW, using global pair-key dedup
          so a fired pair never re-triggers on subsequent iterations.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Tuple

LOOP_WINDOW:                   int   = 4
LOOP_REPEAT_THRESHOLD:         int   = 2
MAX_CONSECUTIVE_FAILURES:      int   = 3
FINGERPRINT_LEN:               int   = 200
SEMANTIC_SIMILARITY_THRESHOLD: float = 0.65

_STOP_WORDS = frozenset({
    "a","an","the","of","in","on","for","to","and","or","is","are",
    "was","with","from","by","at","as","it","this","that","be","have",
    "has","do","does","did","what","who","when","where","how","find",
    "get","give","show","tell","look","search","current","latest",
    "using","please","can","you","me","my","your","about","more",
    "need","try","want","like","just","also","than","then","now",
})


def _tokenize(text: str) -> frozenset:
    tokens = re.findall(r"\b[a-z]\w*\b", text.lower())
    return frozenset(t for t in tokens if t not in _STOP_WORDS and len(t) > 1)


def _jaccard(a: frozenset, b: frozenset) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


@dataclass
class ActionRecord:
    action:       str
    action_input: str
    observation:  str
    success:      bool
    iteration:    int = 0

    @property
    def fingerprint(self) -> str:
        return f"{self.action}::{self.action_input[:FINGERPRINT_LEN].strip()}"

    @property
    def tokens(self) -> frozenset:
        return _tokenize(f"{self.action} {self.action_input}")


class ReflectionEngine:
    def __init__(self) -> None:
        self.history:         List[ActionRecord] = []
        self.replan_count:    int                = 0
        self._reported_pairs: set                = set()

    def record(
        self,
        action:       str,
        action_input: str,
        observation:  str,
        success:      bool,
        iteration:    int = 0,
    ) -> None:
        self.history.append(ActionRecord(
            action       = action,
            action_input = action_input[:FINGERPRINT_LEN],
            observation  = observation[:300],
            success      = success,
            iteration    = iteration,
        ))

    def evaluate(self) -> Tuple[bool, str]:
        if not self.history:
            return False, ""

        # 1. Consecutive failures
        tail = self.history[-MAX_CONSECUTIVE_FAILURES:]
        if (
            len(tail) == MAX_CONSECUTIVE_FAILURES
            and all(not r.success for r in tail)
        ):
            self.replan_count += 1
            return True, (
                f"{MAX_CONSECUTIVE_FAILURES} consecutive failures. "
                f"Last: \"{tail[-1].observation[:100]}\". "
                "Switch tool or approach."
            )

        window = self.history[-LOOP_WINDOW:]
        offset = len(self.history) - len(window)

        # 2. Exact fingerprint loop
        if len(window) >= LOOP_REPEAT_THRESHOLD:
            counts = Counter(r.fingerprint for r in window)
            top_fp, freq = counts.most_common(1)[0]
            if freq >= LOOP_REPEAT_THRESHOLD:
                self.replan_count += 1
                return True, (
                    f"Exact loop: '{top_fp.split('::')[0]}' called {freq}x "
                    f"with identical input in last {len(window)} steps."
                )

        # 3. Semantic loop — fresh window only, deduplicated by global index
        for i in range(len(window)):
            for j in range(i + 1, len(window)):
                ri, rj = window[i], window[j]
                if ri.action != rj.action:
                    continue
                pair_key = (offset + i, offset + j)
                if pair_key in self._reported_pairs:
                    continue
                sim = _jaccard(ri.tokens, rj.tokens)
                if sim >= SEMANTIC_SIMILARITY_THRESHOLD:
                    self._reported_pairs.add(pair_key)
                    self.replan_count += 1
                    return True, (
                        f"Semantic loop: '{ri.action}' called with "
                        f"near-identical intent (similarity={sim:.0%}) "
                        f"at iterations {ri.iteration} and {rj.iteration}. "
                        "Switch to a different tool or approach entirely."
                    )

        return False, ""

    def progress_summary(self) -> str:
        if not self.history:
            return "No actions yet."
        return "\n".join(
            f"  [{'OK  ' if r.success else 'FAIL'}] "
            f"iter={r.iteration:02d}  {r.action}({r.action_input[:80]})"
            for r in self.history
        )

    def recent_failures(self) -> List[str]:
        return [r.observation for r in self.history if not r.success][-3:]