"""
Hard budget enforcer.

Raises BudgetExceeded — a real exception that propagates up and kills execution —
the moment any limit is hit. Never prints a warning and continues.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List


class BudgetExceeded(Exception):
    """Raised when the LLM call count OR cost ceiling is breached.

    This exception is intentionally NOT caught inside the agent loop;
    it propagates to agent.run(), which surfaces a clean partial-result
    report and exits immediately.
    """


@dataclass
class CallRecord:
    call_number: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    label: str
    timestamp: float = field(default_factory=time.time)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class BudgetEnforcer:
    """Tracks LLM call count and simulated USD cost.

    Mock pricing for local Ollama: $0.01 per 1 000 tokens (prompt + completion).
    Hard limits: 10 calls  |  $0.20 total.
    """

    COST_PER_1K_TOKENS: float = 0.01
    MAX_CALLS: int = 10
    MAX_COST: float = 0.20

    def __init__(self) -> None:
        self.calls: int = 0
        self.total_cost: float = 0.0
        self.records: List[CallRecord] = []
        self.completed_steps: List[str] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def calls_remaining(self) -> int:
        return self.MAX_CALLS - self.calls

    @property
    def budget_remaining(self) -> float:
        return self.MAX_COST - self.total_cost

    @property
    def is_critical(self) -> bool:
        """True when ≤2 calls or ≤$0.04 remain — agent should wrap up."""
        return self.calls_remaining <= 2 or self.budget_remaining <= 0.04

    # ------------------------------------------------------------------
    # Enforcement
    # ------------------------------------------------------------------

    def pre_check(self) -> None:
        """Call BEFORE sending any request to the LLM.

        Raises BudgetExceeded immediately if the call count ceiling is already
        reached or the remaining monetary budget is zero.
        """
        if self.calls >= self.MAX_CALLS:
            raise BudgetExceeded(
                f"LLM call limit reached: {self.calls}/{self.MAX_CALLS} calls used. "
                f"Total cost so far: ${self.total_cost:.4f}. Execution stopped."
            )
        if self.total_cost >= self.MAX_COST:
            raise BudgetExceeded(
                f"Monetary limit reached: ${self.total_cost:.4f} >= ${self.MAX_COST:.2f}. "
                f"Calls used: {self.calls}/{self.MAX_CALLS}. Execution stopped."
            )

    def charge(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        label: str = "llm_call",
    ) -> float:
        """Record one completed LLM call and deduct its cost.

        Raises BudgetExceeded if the projected cost would push the total over
        the ceiling.  Returns the cost of this call in USD.

        This is called AFTER the response is received so that real token counts
        from Ollama can be used.  pre_check() must be called BEFORE the request
        to guard against calls that would put us over the call-count limit.
        """
        # Double-check call limit (pre_check is the primary gate, but be safe)
        if self.calls >= self.MAX_CALLS:
            raise BudgetExceeded(
                f"Call limit ({self.MAX_CALLS}) exceeded on charge(). "
                "This is a bug — pre_check() should have fired first."
            )

        total_tokens = max(1, prompt_tokens + completion_tokens)
        cost = (total_tokens / 1_000.0) * self.COST_PER_1K_TOKENS

        if self.total_cost + cost > self.MAX_COST:
            raise BudgetExceeded(
                f"Monetary limit would be exceeded: "
                f"${self.total_cost:.4f} + ${cost:.4f} = "
                f"${self.total_cost + cost:.4f} > ${self.MAX_COST:.2f}. "
                f"Stopping execution immediately."
            )

        self.calls += 1
        self.total_cost += cost
        self.records.append(
            CallRecord(
                call_number=self.calls,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost,
                label=label,
            )
        )
        return cost

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def record_step(self, description: str) -> None:
        """Log a human-readable description of a completed agent step."""
        self.completed_steps.append(description)

    def summary(self) -> str:
        lines = [
            "=" * 50,
            "BUDGET SUMMARY",
            "=" * 50,
            f"LLM Calls Used : {self.calls} / {self.MAX_CALLS}",
            f"Total Cost     : ${self.total_cost:.4f} / ${self.MAX_COST:.2f}",
            f"Remaining Calls: {self.calls_remaining}",
            f"Remaining Budget: ${self.budget_remaining:.4f}",
            "",
            "Call Breakdown:",
        ]
        for r in self.records:
            lines.append(
                f"  #{r.call_number:02d}  {r.label:<30} "
                f"{r.total_tokens:>5} tok  ${r.cost_usd:.4f}"
            )
        if self.completed_steps:
            lines.append("")
            lines.append("Completed Steps:")
            for i, step in enumerate(self.completed_steps, 1):
                lines.append(f"  {i:02d}. {step}")
        lines.append("=" * 50)
        return "\n".join(lines)
