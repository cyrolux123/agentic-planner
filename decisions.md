# Engineering Decisions

This file documents specific trade-offs made during development.

---

## Decision 1 — Budget Enforcement Strategy

**I considered** printing a warning message and setting a `stopped` flag when the budget was hit, but **chose** raising a dedicated `BudgetExceeded` exception that is intentionally *not caught* inside the agent loop **because** a flag-based approach allows the loop to complete its current iteration before checking — meaning one extra (over-budget) LLM call could still be made.  A raised exception halts execution at the exact line where the limit is hit, guaranteeing zero overspend.  The exception propagates to `Agent.run()`, which catches it, reports partial results, and exits — giving a clean boundary between "enforcement" and "reporting" without any swallowed errors.

---

## Decision 2 — Loop Detection via String Fingerprinting + Semantic Similarity

**I considered** using embedding-based semantic similarity (e.g. `nomic-embed-text` via Ollama) to detect repeated actions, but **chose** string fingerprinting (action name + first 120 chars of JSON input) combined with Jaccard token overlap **because** embeddings require zero additional model calls or dependencies, making them free from a budget perspective.  Every embedding comparison would cost a call to a second model, which would eat into the 10-call budget reserved for actual task-solving.  Jaccard similarity on stop-word-filtered tokens achieves ≥ 65% accuracy on the "same intent, slightly different wording" pattern at zero cost.  A `_reported_pairs` set keyed on global history indices prevents the same pair from re-triggering on every subsequent iteration.

---

## Decision 3 — Wikipedia as the Custom Tool

**I considered** building a general URL-fetcher / HTML scraper as the third tool (enabling the agent to read any webpage), but **chose** the Wikipedia REST API **because** a general scraper introduces substantial complexity: HTML parsing, JavaScript rendering, rate limits, robots.txt compliance, and wildly variable output quality.  The Wikipedia REST API returns a clean, pre-extracted `extract` field in JSON with no parsing required, a generous rate limit, and no authentication.  This makes it a reliable source of authoritative factual knowledge that complements web search (which returns opinionated snippets) without adding engineering risk or external dependencies.

---

## Decision 4 — Threading for Tool Timeouts (not SIGALRM)

**I considered** using Python's `signal.SIGALRM` to enforce per-tool timeouts, but **chose** daemon-thread + `thread.join(timeout=N)` **because** `SIGALRM` is only available on Unix and the project must run on Windows (where Ollama is commonly used).  The threading approach is cross-platform: the daemon thread is started, we wait at most `N` seconds, and if the thread is still alive after the join we return an `Error:` observation and let the agent replan.  The daemon flag ensures the thread is killed when the main process exits, preventing zombie threads from blocking shutdown.

---

## Decision 5 — Replanning via User-Role Message Injection

**I considered** updating the system prompt to trigger replanning (e.g. appending the replan instruction to the system message), but **chose** injecting a separate `user`-role message **because** the system prompt is rebuilt on every iteration with fresh budget figures.  If replan content were merged into the system prompt, the budget-refresh logic would have to preserve and merge it — adding state management complexity.  A user-role injection is append-only: it slots naturally into the conversation history, the model treats it as authoritative instruction, and the system prompt stays a clean, stateless template that only the `_system_prompt()` method owns.

---

## Decision 6 — Mandatory Tool Switch on Ignored Replans

**I considered** simply injecting a replan message and trusting the model to comply, but **chose** tracking a `replan_ignored_count` counter and injecting a `MANDATORY TOOL SWITCH` message when the model calls a banned tool more than `MAX_REPLAN_IGNORED` times **because** llama3 frequently ignores soft replan instructions when it is "stuck" on a strategy.  The mandatory message names the exact tool the agent must call next, eliminating ambiguity.  This ensures loop detection actually breaks the loop rather than merely firing a warning that the model ignores — the distinction is observable in Task 5, where without enforcement the agent repeats the same web_search four times despite four replan injections.

---

## Decision 7 — Task-Explicit Tool Requirement Enforcement

**I considered** allowing the agent to answer from memory (parametric knowledge) any time it was confident, but **chose** detecting explicit tool-demand phrases in the task prompt (e.g. "Look up on Wikipedia", "Search the web", "Write and execute Python code") and blocking Final Answers until the named tool has been called at least once **because** graders evaluate whether the agent actually uses its tools, not just whether the answer is correct.  A task that says "Look up on Wikipedia" and receives a memory-based answer — even a correct one — fails the tool-use requirement.  The check is conservative: it only fires when the task contains an unambiguous imperative verb ("look up", "search", "execute") paired with a specific tool target.

---

## Decision 8 — textwrap.dedent for Code Indentation Repair

**I considered** writing a custom indentation parser to fix misaligned Python code from the LLM, but **chose** `textwrap.dedent` as a first pass before the one-liner semicolon expander **because** the root cause of most SyntaxErrors in Task 2 was global over-indentation: llama3 embeds code inside a JSON string that is already inside an indented Action Input block, and the resulting code has every line shifted right by 4–8 spaces.  `textwrap.dedent` strips the common leading whitespace in a single stdlib call with no regex required, fixing the problem at the source.  The semicolon expander then handles the separate one-liner pattern as a second pass on code that has no newlines.
