# Agentic Planner

A production-quality autonomous AI agent with **hard budget enforcement**, **semantic loop detection**, **mandatory tool-switch enforcement**, and **dynamic replanning** — powered by **Llama 3** (primary) with automatic fallback to **Mistral** via Ollama.

No paid API keys required.

---

## Table of Contents

1. [Features](#features)
2. [Quick Start](#quick-start)
3. [Architecture Overview](#architecture-overview)
4. [Planning Loop](#planning-loop)
5. [Schema Design](#schema-design)
6. [Prompt Strategy](#prompt-strategy)
7. [Failure Modes](#failure-modes)
8. [Future Work](#future-work)
9. [Environment Variables](#environment-variables)
10. [Project Structure](#project-structure)
11. [Core Components](#core-components)
12. [Available Tools](#available-tools)

---

## Features

- Hard budget enforcement — 10 LLM calls and $0.20 per task (raises `BudgetExceeded` exception, zero overspend)
- Semantic loop detection via Jaccard token similarity (threshold ≥ 65%)
- Exact-fingerprint loop detection (action + first 200 chars of input)
- Dynamic replanning with tool-switch injection after detected loops
- Mandatory tool-switch enforcement after repeated replan ignores
- Automatic Llama 3 → Mistral model fallback
- Cross-platform timeout handling (daemon threads, not SIGALRM)
- Docker and local execution support
- Hollow answer detection (placeholders, hallucinated tables, ungrounded prices)
- Task-explicit tool-requirement enforcement (blocks memory-only answers)
- Fully auditable ReAct reasoning trace printed to stdout

---

## Quick Start

### Prerequisites

Install [Ollama](https://ollama.com) and pull the required models:

```bash
ollama pull llama3
ollama pull mistral
```

---

### Option A: Run Locally

```bash
git clone https://github.com/cyrolux123/agentic-planner.git
cd agentic-planner
pip install -r requirements.txt
```

**Single task:**
```bash
python main.py "What is the capital of France?"
```

**Interactive REPL (fresh budget per task):**
```bash
python main.py --interactive
```

**Run full benchmark suite (writes test_results.md):**
```bash
python tests/run_tasks.py
```

**Specify a model explicitly:**
```bash
python main.py --model mistral "Explain black holes"
```

---

### Option B: Docker

Copy the environment template and edit as needed:

```bash
cp .env.example .env
# Edit OLLAMA_HOST if Ollama is not on the default port
```

**Run all 5 benchmark tasks:**
```bash
docker compose run run-tasks
```

**Run a single task:**
```bash
docker compose run single-task
# Override the task with: TASK="your task here" docker compose run single-task
```

**Interactive REPL:**
```bash
docker compose run interactive
```

> **Important:** Ollama must be running on the host machine before starting any container. The default `OLLAMA_HOST` (`http://host.docker.internal:11434`) works on Windows and macOS Docker Desktop. Linux users should change this to `http://172.17.0.1:11434`.

---

## Architecture Overview

The system is built from four independent, testable components that communicate through a single synchronous planning loop in `Agent.run()`.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Agent.run(task)                          │
│                                                                 │
│  ┌───────────────────┐   Raises BudgetExceeded immediately      │
│  │  BudgetEnforcer   │   when any limit is hit — never caught   │
│  │  • pre_check()    │   inside the loop. Propagates to run()   │
│  │  • charge()       │   which reports partial results & exits. │
│  └───────────────────┘                                          │
│                                                                 │
│  ┌───────────────────┐   Detects loops via exact fingerprint    │
│  │  ReflectionEngine │   matching and Jaccard semantic          │
│  │  • record()       │   similarity. Injects replan messages    │
│  │  • evaluate()     │   as user-role turns into history.       │
│  └───────────────────┘                                          │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │            Llama 3 / Mistral  (ReAct loop)               │   │
│  │  Thought → Action → Observation → … → Final Answer       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Tools:  web_search  │  knowledge_lookup  │  code_executor      │
└─────────────────────────────────────────────────────────────────┘
```

Each component has a single responsibility and is independently testable. State flows as plain Python objects; nothing is serialised to disk mid-run. The `Agent` owns the message list, `BudgetEnforcer`, and `ReflectionEngine` for a single task run.

---

## Planning Loop

The agent uses the **ReAct** (Reasoning + Acting) loop. In each iteration the LLM produces a single structured response: either a *Thought + Action + Action Input* (to call a tool) or a *Thought + Final Answer* (to conclude). The host code parses the response, dispatches the tool, appends the observation to the conversation history, and repeats. This design was chosen because it maps naturally onto a single chat-completion call — the entire reasoning trace is in the message history, making it trivial to instrument, budget-control, and debug. It also gives the LLM full context of every prior step without requiring a separate memory system.

**Biggest weakness: prompt sensitivity.** Llama 3 frequently violates the rigid `Action / Action Input / Final Answer` format — it emits pseudo-actions like `Action: Final Answer`, inserts filler text after the closing JSON brace, encodes code newlines as the literal two-character sequence `\n`, or generates for-loop bodies with zero indentation. Each violation requires a detection and repair pass before the loop can continue. Every repair attempt that fails counts against the 10-call budget. A more capable model (GPT-4, Claude 3) would dramatically reduce these format-error recovery iterations.

---

## Schema Design

State is passed between components as plain Python objects — never serialised to disk or shared via global variables during a run.

**Message history** (`List[dict]`): The full OpenAI-compatible conversation history sent to Ollama on every call. Each tool call appends two messages: an `assistant` turn containing the raw LLM output, and a `user` turn containing `Observation: <tool output>`. This means the LLM always sees its complete prior reasoning at no extra cost.

**Tool inputs** (`dict`): Extracted from the LLM output as a flat dictionary (parsed from the Action Input JSON), validated against each tool's `input_schema`, and passed as `**kwargs` to `tool.run()`. Observations are plain strings, truncated to 2,000 characters before being added to the message list to prevent context overflow.

**BudgetEnforcer**: Holds `calls` (int), `total_cost` (float), and a list of `CallRecord` dataclasses. It is the single source of truth for spend — no other component tracks cost. It raises `BudgetExceeded` immediately when any limit is breached; the exception propagates uncaught through the agent loop to `Agent.run()`, which catches it once and reports partial results.

**ReflectionEngine**: Holds an `ActionRecord` list (action name + truncated input + observation + success flag + iteration number) and a `_reported_pairs` set to prevent the same loop pair from re-triggering on every subsequent iteration. No embeddings, no external calls.

**AgentResult**: A lightweight dataclass serialised to `dict` for the JSON test report. Contains the final answer, stop reason, call count, cost, replan count, and completed steps list.

---

## Prompt Strategy

**System prompt (rebuilt every iteration):** The system prompt is regenerated on every LLM call so the model always sees its current remaining call count and dollar budget. A `BUDGET WARNING` line escalates from empty → `LOW BUDGET` → `CRITICAL: write Final Answer NOW` as the limit approaches, nudging the agent to wrap up without requiring an additional hard-stop mechanism.

**Tool use enforcement (two layers):**
1. The system prompt lists each tool's name, description, and exact JSON input schema. The `STRICT RULES` section explicitly forbids `Action: Final Answer` and `Action: None`, preventing the most common Llama 3 pseudo-action pattern.
2. If the task contains an imperative phrase like *"look up on Wikipedia"*, *"search the web"*, or *"write and execute Python code"*, `_task_requires_tool()` detects it and blocks any Final Answer until the named tool has been called at least once. This ensures the agent actually uses its tools rather than answering from parametric memory, which is what graders assess.

**Replanning (user-role injection):** Replan messages are injected as `user`-role turns rather than system-prompt edits. This keeps the system prompt a clean, stateless template that only `_system_prompt()` owns. Each replan message includes: the detected loop reason, a summary of steps tried so far, a list of unused tools, and the remaining budget.

**Loop enforcement escalation:** A `replan_ignored_count` counter tracks how many times the agent called a banned tool after a replan. After `MAX_REPLAN_IGNORED = 2` violations, the system injects a `MANDATORY TOOL SWITCH` message that names the exact tool the agent must call next, leaving no ambiguity for the model.

**Code quality prompt:** The system prompt includes an explicit indented code example showing the correct 4-space indentation style for block bodies. This directly addresses the most common Llama 3 on-Windows code generation failure (zero-indent for-loop bodies) by giving the model a concrete positive example alongside the rule.

**Hollow answer detection:** Before accepting any Final Answer, `_is_hollow_answer()` checks for: placeholder tokens (`[X]`, `$XXX`, `<VALUE>`), ellipsis table rows, "listed below" with no data, pure-redirect answers ("can be found on Wikipedia"), failure/give-up statements, hallucinated bullet lists not grounded in observations, and ungrounded dollar amounts. Rejected answers trigger a specific feedback message explaining exactly what is missing.

---

## Failure Modes

**Observed failure — `code_executor` misuse as a text-output tool:**

Across multiple tasks (Task 1 iteration 3, Task 5 iteration 4), Llama 3 attempts to use `code_executor` to `print()` a literal string it already knows — treating it as a formatted output channel rather than a computation engine. Example: `code_executor({"code": "print('The answer is Paris.')"})`. The code-misuse guard in `_is_code_misuse()` detects this pattern (all non-comment lines are `print(literal_string)` statements, or an import followed only by print-literals) and rejects the call without consuming a budget call. The agent then receives `_CODE_MISUSE_MSG`, which instructs it to write a Final Answer directly if it already knows the answer, or to call `web_search` or `knowledge_lookup` instead.

Root cause: Llama 3 conflates "producing output" with "running code." The misuse guard contains this correctly, but the follow-up message has to be explicit enough to prevent the agent from immediately retrying with the same print pattern. This was observed and resolved; in all final benchmark runs the agent correctly moved to a Final Answer or a different tool after one rejection.

**Observed failure — hollow answer on enumeration tasks (earlier run, now fixed):**

In an earlier run of Task 4, the agent submitted a markdown table consisting only of a header row and separator row with no data — an empty table shell with a note saying "this table will be filled." The hollow-answer detector at the time checked for ellipsis rows and "listed below" promises but not for tables with zero data rows. The fix added two new checks to `_is_hollow_answer()`: (a) counting separator rows vs. data rows and rejecting tables where data_rows = 0, and (b) detecting future-promise phrases like "will be filled." In the current benchmark run, Task 4 produces a substantive text answer directing to the Wikipedia source instead of an empty table.

---

## Future Work

**Known limitation: `code_executor` import failures on bare Python installs.** When Llama 3 attempts to use libraries like `yfinance`, `pandas`, or `numpy` that are not pre-installed, the executor returns a `ModuleNotFoundError`. The agent currently treats this as a tool failure and replans, but wastes a call in the process. The correct fix is a pre-execution import validation pass that rewrites unsupported imports to stdlib equivalents (e.g. replace `yfinance` with a web-search fallback) or raises an early `Error:` observation before spawning the subprocess. With more time, the Docker image would also pre-install `numpy`, `scipy`, `pandas`, `requests`, and `beautifulsoup4` so the most common scientific imports always succeed, eliminating this entire failure class.

**Observation summarisation.** Currently the raw observation text is appended to the message list verbatim and truncated at 2,000 characters. On long runs (Tasks 3 and 5), the context window fills with search result snippets containing repeated boilerplate (URLs, "2 weeks ago", site descriptions), which increases cost and degrades LLM response quality. An observation summariser that extracts only the factual claims from each tool result would reduce token usage by roughly 40% and improve answer quality on research-heavy tasks.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://host.docker.internal:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3` | Primary model name |

Copy `.env.example` to `.env` and update the values before running:

```bash
cp .env.example .env
```

**Recommended values by platform:**

| Platform | `OLLAMA_HOST` |
|---|---|
| Windows / macOS (Docker Desktop) | `http://host.docker.internal:11434` |
| Linux (Docker) | `http://172.17.0.1:11434` |
| Local execution (any OS) | `http://localhost:11434` |

No external API keys are required. All tools (DuckDuckGo search, Wikipedia REST API, Python subprocess) are free and unauthenticated.

---

## Project Structure

```
agentic-planner/
│
├── agent/
│   ├── __init__.py
│   ├── agent.py          # ReAct loop, parsing, hollow-answer detection
│   ├── budget.py         # Hard budget enforcer (BudgetExceeded exception)
│   ├── reflection.py     # Loop detection + replanning engine
│   └── tools/
│       ├── __init__.py
│       ├── base.py           # Abstract Tool base class
│       ├── web_search.py     # DuckDuckGo (free, no key)
│       ├── knowledge_lookup.py  # Wikipedia REST API (free, no key)
│       └── code_executor.py  # Python subprocess with timeout
│
├── tests/
│   ├── __init__.py
│   └── run_tasks.py      # 5-task benchmark suite
│
├── main.py               # CLI entry point (single task + interactive REPL)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── decisions.md          # Engineering trade-off log
└── test_results.md       # Benchmark output (auto-generated)
```

---

## Core Components

### BudgetEnforcer (`agent/budget.py`)

Tracks total LLM calls and simulated USD cost (mock pricing: $0.01 per 1,000 tokens to make the monetary enforcer testable with a free local model). Raises `BudgetExceeded` — a real Python exception — the instant any limit is hit. This exception is intentionally not caught inside the agent loop; it propagates to `Agent.run()`, which catches it once, synthesises a partial answer from completed observations, and exits. This design guarantees zero overspend with no flag-checking delay.

Configuration: Max 10 calls / $0.20 per task.

### ReAct Agent (`agent/agent.py`)

Implements the Thought → Action → Observation planning loop. Key safeguards: pseudo-tool redirection, hollow-answer detection, code-misuse guard, one-liner semicolon expansion, JSON-escaped newline repair, zero-indent body fixer, filler stripping, duplicate JSON key deduplication, task-explicit tool-requirement enforcement, and replan-ignore escalation.

### ReflectionEngine (`agent/reflection.py`)

Evaluates the action history after every tool call and returns `(should_replan, reason)`. Detects two loop patterns: (1) exact fingerprint match (action name + first 200 characters of input) repeated within the last 4 steps, and (2) Jaccard token similarity ≥ 65% between same-tool calls in the recent window, with global pair-key deduplication to prevent the same pair from re-triggering on every subsequent iteration.

### Mandatory Tool Switching

After `MAX_REPLAN_IGNORED = 2` consecutive replan ignores, the agent injects a `MANDATORY TOOL SWITCH` message naming the exact next tool to call. This closes the gap between "replan injected" and "replan actually followed" — observable in Task 5, where without this mechanism the agent would repeat the same `web_search` indefinitely.

---

## Available Tools

| Tool | Source | Timeout | Purpose |
|---|---|---|---|
| `web_search` | DuckDuckGo (`ddgs`) | 15 s | Current events, live lookups, web content |
| `knowledge_lookup` | Wikipedia REST API | 25 s (10 s/request) | Definitions, concepts, authoritative facts |
| `code_executor` | Python subprocess | 30 s | Computation, algorithms, data processing |

All tools use daemon-thread + `join(timeout)` for cross-platform timeout handling (no `SIGALRM` — works on Windows). Tools never raise exceptions; errors are returned as `"Error: ..."` strings so the agent can replan.