# Agentic Planner

A production-quality autonomous AI agent with **hard budget enforcement**, **semantic loop detection**, **mandatory tool-switch enforcement**, and **dynamic replanning**, powered by **Llama 3** (primary) with automatic fallback to **Mistral** via Ollama.

No paid API keys required.

---

## Features

-  Hard budget enforcement (LLM calls + cost limits)
-  Semantic loop detection using Jaccard similarity
-  Dynamic replanning and reflection
-  Mandatory tool switching after repeated failures
-  Automatic Llama3 → Mistral fallback
-  Cross-platform timeout handling
-  Docker and local execution support
-  Fully auditable ReAct reasoning loop

---

## Quick Start

### Prerequisites

Install Ollama:

https://ollama.com

Pull the required models:

```bash
ollama pull llama3
ollama pull mistral
```

---

## Option A: Run Locally

```bash
git clone https://github.com/cyrolux123/agentic-planner.git
cd agentic-planner

pip install -r requirements.txt
```

### Single Task

```bash
python main.py "What is the capital of France?"
```

### Interactive Mode

```bash
python main.py --interactive
```

### Run Benchmark Suite

```bash
python tests/run_tasks.py
```

Results are written to:

```text
test_results.md
```

---

## Option B: Docker

Copy the environment template:

```bash
cp .env.example .env
```

Edit `OLLAMA_HOST` if necessary.

### Run Benchmark Tasks

```bash
docker compose run run-tasks
```

### Run a Single Task

```bash
docker compose run single-task
```

### Interactive Mode

```bash
docker compose run interactive
```

> **Important:** Ollama must be running on the host machine before starting the container.

---

## Environment Variables

| Variable | Default | Description |
|-----------|-----------|-----------|
| `OLLAMA_HOST` | `http://host.docker.internal:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3` | Primary model |

### Recommended Values

#### Windows / macOS Docker Desktop

```text
http://host.docker.internal:11434
```

#### Linux Docker

```text
http://172.17.0.1:11434
```

#### Local Execution

```text
http://localhost:11434
```

---

# Architecture

The system consists of four independent, testable components connected through a synchronous planning loop.

```text
┌─────────────────────────────────────────────────────────────┐
│                     Agent.run(task)                         │
│                                                             │
│  ┌──────────────────┐                                       │
│  │ BudgetEnforcer   │                                       │
│  │ • pre_check()    │                                       │
│  │ • charge()       │                                       │
│  └──────────────────┘                                       │
│                                                             │
│  ┌──────────────────┐      ┌──────────────────────────┐     │
│  │ ReflectionEngine │ ---> │ Llama3 / Mistral         │     │
│  │ • evaluate()     │      │ ReAct Prompt Loop        │     │
│  └──────────────────┘      └──────────────────────────┘     │
│                                                             │
│  Tools                                                      │
│   • web_search                                              │
│   • knowledge_lookup                                        │
│   • code_executor                                           │
└─────────────────────────────────────────────────────────────┘
```

---

## Core Components

### BudgetEnforcer

Location:

```text
agent/budget.py
```

Responsibilities:

- Tracks total LLM calls
- Tracks estimated token costs
- Enforces hard limits
- Raises `BudgetExceeded` immediately

Configuration:

```text
Max Calls : 10
Max Cost  : $0.20
Pricing   : $0.01 / 1K tokens
```

---

### ReAct Agent

Location:

```text
agent/agent.py
```

Responsibilities:

- Thought → Action → Observation loop
- Tool execution
- Final answer generation
- Budget-aware reasoning

Key safeguards:

- Action takes precedence over Final Answer
- Redirects pseudo-tools (`final`, `none`, `answer`)
- Hallucination detection
- Explicit tool-requirement enforcement
- Python code sanitisation

---

### Reflection Engine

Location:

```text
agent/reflection.py
```

Responsibilities:

- Progress evaluation
- Loop detection
- Replanning recommendations
- Tool diversification

Loop detection methods:

1. Exact fingerprint matching
2. Semantic similarity (Jaccard ≥ 0.65)

---

### Mandatory Tool Switching

If the model repeatedly ignores replanning instructions:

```text
MAX_REPLAN_IGNORED = 2
```

The system injects:

```text
MANDATORY TOOL SWITCH
```

forcing the next tool selection.

---

## Available Tools

| Tool | Purpose | Timeout |
|--------|---------|---------|
| `web_search` | DuckDuckGo search | 15 s |
| `knowledge_lookup` | Wikipedia lookup | 10 s |
| `code_executor` | Python execution | 30 s |

All tools use daemon-thread based timeout handling for cross-platform compatibility.

---

## Project Structure

```text
agentic-planner/
│
├── agent/
│   ├── __init__.py
│   ├── agent.py
│   ├── budget.py
│   ├── reflection.py
│   └── tools/
│       ├── __init__.py
│       ├── base.py
│       ├── web_search.py
│       ├── knowledge_lookup.py
│       └── code_executor.py
│
├── tests/
│   ├── __init__.py
│   └── run_tasks.py
│
├── main.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── decisions.md
└── test_results.md
```

---

## Future Improvements

Planned enhancements:

- Pre-installed scientific packages:
  - NumPy
  - Pandas
  - Requests
  - BeautifulSoup4

- Import validation before execution

- Automatic rewrite of unsupported imports

- Observation summarisation to reduce context growth

- More advanced reflection heuristics

---
