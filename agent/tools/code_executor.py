"""
Code Execution Tool — runs arbitrary Python in an isolated subprocess.

Security notes:
- subprocess isolates the child from the agent's memory space.
- Running inside Docker provides OS-level sandboxing.
- stdout + stderr are both captured; the process cannot interact with stdin.

Timeout: 30 seconds.  subprocess.TimeoutExpired is caught and surfaced as
an "Error:" observation so the agent can replan without crashing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from typing import Optional

from .base import Tool


TOOL_TIMEOUT: int = 30   # seconds
MAX_OUTPUT_CHARS: int = 3_000  # truncate runaway output


def _repair_indentation(code: str) -> str:
    """
    Strip common leading whitespace so code pasted into JSON doesn't break.

    When llama3 embeds code inside a JSON string, it sometimes adds a global
    indent level (all lines shifted right by 4-8 spaces).  textwrap.dedent
    removes the common leading whitespace, then we strip trailing spaces per
    line to prevent mixed-whitespace IndentationErrors.
    """
    dedented = textwrap.dedent(code)
    lines = [line.rstrip() for line in dedented.splitlines()]
    return "\n".join(lines).strip()


class CodeExecutorTool(Tool):
    name = "code_executor"
    description = (
        "Execute Python 3 code and return stdout/stderr. "
        "Use for calculations, algorithms, data processing, and verification. "
        "Code runs in an isolated subprocess — no side effects on the agent. "
        "Do NOT use just to print text — use Final Answer for that."
    )
    input_schema = {
        "code": "string — valid Python 3 source code to execute",
    }

    def run(self, code: str = "", **_kwargs) -> str:  # type: ignore[override]
        code = (code or "").strip()
        if not code:
            return "Error: 'code' parameter is required and cannot be empty."

        # Repair indentation before execution
        code = _repair_indentation(code)

        tmp_path: Optional[str] = None
        try:
            # Write code to a temp file so argv[0] is meaningful in tracebacks
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                delete=False,
                encoding="utf-8",
            ) as fh:
                fh.write(code)
                tmp_path = fh.name

            proc = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=TOOL_TIMEOUT,
            )

            parts = []
            if proc.stdout:
                parts.append(f"STDOUT:\n{proc.stdout.strip()[:MAX_OUTPUT_CHARS]}")
            if proc.stderr:
                parts.append(f"STDERR:\n{proc.stderr.strip()[:MAX_OUTPUT_CHARS]}")

            if not parts:
                return (
                    f"Code executed successfully "
                    f"(exit code {proc.returncode}) with no output."
                )

            output = "\n\n".join(parts)
            if proc.returncode != 0:
                output = f"Exit code: {proc.returncode}\n\n" + output

            return output

        except subprocess.TimeoutExpired:
            return (
                f"Error: Code execution timed out after {TOOL_TIMEOUT}s. "
                "Likely an infinite loop. Refactor the algorithm."
            )
        except OSError as exc:
            return f"Error: Could not write/run temp file — {exc}"
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
