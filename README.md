# Resource-Constrained Agentic Planning Loop

A production-quality autonomous AI agent with **hard budget enforcement**,
**semantic loop detection**, **mandatory tool-switch enforcement**, and
**dynamic replanning** — powered by **llama3** (primary) or **mistral**
(automatic fallback) via Ollama. No paid API keys required.

---

## Quick Start

### Prerequisites

```bash
# Install Ollama: https://ollama.com
ollama pull llama3     # primary model
ollama pull mistral    # fallback (recommended)
```

### Option A — Local (no Docker)

```bash
git clone <repo-url>
cd agentic-planner
pip install -r requirements.txt

# Single task
python main.py "What is the capital of France?"

# Interactive REPL (fresh budget per task)
python main.py --interactive

# Run all 5 benchmark tasks → writes test_results.md
python tests/run_tasks.py
```

### Option B — Docker (recommended for reproducibility)

```bash
cp .env.example .env        # edit OLLAMA_HOST if needed

docker compose run run-tasks     # all 5 benchmark tasks
docker compose run single-task   # single task via TASK env var
docker compose run interactive   # interactive REPL
```

> **Note:** Ollama must be running on your **host machine** before starting
> the container. The container connects to it via `OLLAMA_HOST`.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://host.docker.internal:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3` | Primary model (auto-falls back to `mistral`) |

Copy `.env.example` → `.env` and adjust `OLLAMA_HOST`:
- **Windows / macOS Docker Desktop:** `http://host.docker.internal:11434`
- **Linux Docker:** `http://172.17.0.1:11434`
- **No Docker:** `http://localhost:11434`

---

## Architecture Overview

Four separable, independently testable components wired together in a
single synchronous loop:

```
┌─────────────────────────────────────────────────────────────┐
│                     Agent.run(task)                          │
│                                                             │
│  ┌──────────────────┐  raises BudgetExceeded → STOP         │
│  │  BudgetEnforcer   │  tracks calls + simulated cost        │
│  │  pre_check()      │  $0.01 / 1k tokens (mock pricing)    │
│  │  charge()         │  hard limits: 10 calls / $0.20       │
│  └──────────────────┘                                       │
│                                                             │
│  ┌──────────────────┐  ┌──────────────────────────────┐    │
│  │  ReflectionEngine │  │   Ollama / llama3            │    │
│  │  evaluate()       │  │   (ReAct prompt loop)        │    │
│  │  → replan msg     │  └──────────────────────────────┘    │
│  │  → mandatory      │                                      │
│  │    tool switch    │                                      │
│  └──────────────────┘                                       │
│                                                             │
│  Tools                                                      │
│    web_search        DuckDuckGo,    15 s daemon-thread      │
│    code_executor     subprocess,    30 s timeout            │
│    knowledge_lookup  Wikipedia API, 10 s daemon-thread      │
└─────────────────────────────────────────────────────────────┘
```

**BudgetEnforcer** (`agent/budget.py`) raises `BudgetExceeded` — a hard
exception never caught inside the loop — the instant either limit is hit.
Simulates token cost at $0.01/1k tokens so the monetary enforcer is
visibly active on local models.

**ReAct Agent** (`agent/agent.py`) drives the Thought → Action →
Observation cycle. Key behaviours: (1) Action always beats Final Answer
in the same response; (2) pseudo-tool names (`final`, `none`, `answer`)
are redirected to Final Answer parsing instead of tool dispatch; (3) hollow
answer detector rejects ellipsis tables, "listed below" with no data, and
dollar amounts not grounded in any real observation; (4) `_sanitise_code`
uses `textwrap.dedent` to fix global over-indentation from JSON embedding,
then expands one-liner semicolon chains into properly indented Python;
(5) tasks containing explicit tool-demand phrases ("look up on Wikipedia",
"search the web", "write and execute Python code") block Final Answers
until the named tool has been called at least once.

**ReflectionEngine** (`agent/reflection.py`) evaluates progress after
every tool call. Detects loops at two levels: exact fingerprint match
(identical retries) and Jaccard token similarity ≥ 0.65 on same-tool
calls within a sliding window. A `_reported_pairs` set keyed on global
history indices prevents the same pair from re-triggering replanning on
every subsequent iteration.

**Mandatory Tool Switch** (`agent/agent.py`): when the model ignores a
replan message and calls a banned tool again, a `replan_ignored_count`
counter increments. After `MAX_REPLAN_IGNORED` (=2) ignored replans, a
`MANDATORY TOOL SWITCH` message names the exact next tool the agent must
call — eliminating the "replan fires but agent ignores it" failure mode
observed in adversarial tasks.

**Tools** (`agent/tools/`) use daemon-thread + `join(timeout=N)` for all
timeouts — cross-platform, no `SIGALRM`. No bare `except: pass` anywhere.

---

## Planning Loop

**Why ReAct?** ReAct (Yao et al., 2022) interleaves explicit `Thought`
steps with tool calls in a plain-text format that instruction-tuned models
follow without fine-tuning. Every thought is auditable — you can read the
agent's reasoning step by step — which is essential for verifying budget
and replanning behaviour during evaluation.

**Biggest weakness:** Compounding context length. Every iteration appends
the full tool observation to the conversation. Token usage and therefore
cost grow linearly with step count, which is damaging under a $0.20
budget. Mitigated by truncating observations to 2,000 characters, capping
`num_predict` at 400 tokens, and refreshing the system prompt with live
budget figures on every turn — but linear growth remains the primary
scaling bottleneck.

---

## Schema Design

**All state flows through the `messages` list** — a standard list of
`{"role": ..., "content": ...}` dicts (OpenAI-compatible format). No
separate state database is needed. The loop is trivially resumable by
appending to the list. Observations are user messages prefixed with
`"Observation: "`. Replanning injections are also user messages, keeping
the system prompt a clean stateless template.

**Tool I/O is JSON-keyed.** Each tool declares `input_schema: Dict[str,
str]` rendered verbatim into the system prompt so the model sees exact key
names and types. The parser strips markdown fences, deduplicates repeated
keys (keeping first occurrence — llama3 emits `{"query":"A","query":"B"}`
with Python's `json.loads` taking the last), and unwraps nested tool-call
formats. A two-pass code sanitiser first strips common leading whitespace
via `textwrap.dedent` (fixing global over-indentation from JSON embedding),
then converts one-liner semicolon chains into properly indented Python —
but only when a block-opening colon is detected before a semicolon, never
touching already-correct multi-line code.

**Hallucination grounding.** An `_all_observations` list accumulates every
real tool output during the run. Before accepting a Final Answer, the
hollow-answer detector checks any dollar amounts against this corpus —
rejecting prices that never appeared in actual tool output.

**Correct success/failure labelling.** A `code_executor` call that returns
exit code 1 with STDERR is recorded as `failed`, not `success` — the
`effective_success` flag checks for `"Exit code: 1"` in the observation
string and overrides the surface-level tool success indicator.

**Budget and reflection state** are pure in-memory dataclasses. Not
serialised between runs — intentional for simplicity. Each `Agent.run()`
starts fresh.

---

## Prompt Strategy

The system prompt is **rebuilt on every iteration** with the current
remaining call count and dollar budget so the model reads:
`LLM calls: 3 remaining of 10 | Cost: $0.1234 remaining of $0.20`.

Structural layers:

**1. Budget block (top)** — in the model's primary attention window. When
≤2 calls remain, a `WARNING` line instructs the model to write Final
Answer immediately.

**2. Tool descriptions** — exact JSON key names and types, deliberately
brief to reduce prompt tokens and prevent the model from reproducing the
full section verbatim. An explicit note states: "Do NOT use code_executor
just to print text — use Final Answer for that."

**3. Format specification** — two named patterns (PATTERN 1 / PATTERN 2)
with one critical rule per line. The most important rule is explicit:
*"Never write 'Action: Final Answer' or 'Action: None' — use PATTERN 2
directly."* This eliminates the most common llama3 confusion pattern.
An additional rule: *"If the task explicitly says 'look up' or 'search',
you MUST call the relevant tool before writing a Final Answer."*

**4. Stop tokens** — `"\nBUDGET\n"`, `"\nTOOLS\n"`, and
`"\nRESPONSE FORMAT"` added to Ollama's stop list. This cuts off the
response the moment llama3 tries to echo a system-prompt section header.

**5. Replanning injection** — delivered as a `user`-role message with an
explicit list of unused tools to try next. If the model ignores this and
calls a banned tool again, a `MANDATORY TOOL SWITCH` message names the
exact tool to call — no ambiguity left.

---

## Failure Modes

**Observed — Code indentation errors (Task 2):**
llama3 embeds Python code inside a JSON Action Input string. Because JSON
strings are often indented within the LLM's output, the resulting code can
have every line shifted right by 4–8 spaces, causing `IndentationError` or
`SyntaxError` at runtime. Fix: `textwrap.dedent` strips common leading
whitespace before the code is written to the temp file. Without this fix,
both `code_executor` calls in Task 2 returned exit code 1 and the agent
fell back to a hallucinated (wrong) answer.

**Observed — Replan messages being ignored (Task 5):**
After the reflection engine fires and injects a replan, llama3 sometimes
calls the same banned tool immediately on the next iteration. A soft replan
message alone is insufficient. Fix: `replan_ignored_count` tracks repeat
offences; after `MAX_REPLAN_IGNORED` violations, a `MANDATORY TOOL SWITCH`
message names the exact tool the agent must call next — the model cannot
misinterpret it.

**Observed — Adversarial task 4 produces a non-answer:**
Without enforcement, the agent's Final Answer for the capitals enumeration
task was "The capital cities of every country can be found by searching..."
— a method description, not a partial result. This is a hollow answer and
is now caught by the redirect detector and the failure-pattern detector,
forcing the agent to either produce actual partial data from its observations
or try another tool.

---

## Future Work

**Known limitation:** The `code_executor` subprocess runs with only the
Python standard library available. Third-party packages (`pandas`,
`yfinance`, `numpy`) are not installed, so the agent receives
`ModuleNotFoundError` when llama3 generates imports for them. This wastes
1-2 calls on failed attempts before the reflection engine triggers
replanning.

With more time I would add a curated allow-list of safe, pre-installed
packages (`requests`, `numpy`, `beautifulsoup4`) to the Docker image and
inject a guard at the top of `_sanitise_code` that detects unknown imports
and either rewrites the code to use stdlib equivalents or immediately
returns an `Error:` observation — saving the subprocess round trip and the
budget call entirely.

---

## Project Structure

```
agentic-planner/
├── agent/
│   ├── __init__.py
│   ├── agent.py              # ReAct loop, parser, code sanitiser,
│   │                         # hollow-answer detector, mandatory tool switch,
│   │                         # task-explicit tool requirement enforcement
│   ├── budget.py             # Hard budget enforcer (calls + cost)
│   ├── reflection.py         # Loop detection and replanning engine
│   └── tools/
│       ├── __init__.py
│       ├── base.py           # Abstract Tool base class
│       ├── web_search.py     # DuckDuckGo, 15 s daemon-thread timeout
│       ├── code_executor.py  # Python subprocess, 30 s timeout,
│       │                     # textwrap.dedent indentation repair
│       └── knowledge_lookup.py  # Wikipedia REST API, 10 s timeout
├── tests/
│   ├── __init__.py
│   └── run_tasks.py          # 5 benchmark tasks + markdown reporter
├── main.py                   # CLI: single task + interactive REPL,
│                             # llama3→mistral auto-fallback
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
├── decisions.md
└── test_results.md           # auto-generated by tests/run_tasks.py
```
#   a g e n t i c - p l a n n e r  
 