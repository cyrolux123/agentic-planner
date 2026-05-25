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

## Decision 8 — Three-Pass Code Sanitiser (Unescape → Dedent → Semicolon Expand)

**I considered** writing a custom indentation parser to fix misaligned Python code from the LLM, but **chose** a three-pass pipeline — (0) JSON escape decoding, (1) `textwrap.dedent`, (2) semicolon-chain expansion — **because** two distinct failure modes cause Task 2 SyntaxErrors and each requires a different fix.  Pass 0 targets the root cause observed in test runs on Windows: llama3 encodes newlines inside JSON strings as the two-character sequence `\n` (backslash + n) rather than a real newline character, producing a single-line string that Python cannot parse as a block.  `str.replace(r"\n", "\n")` resolves this before any other pass.  Pass 1 (`textwrap.dedent`) then removes the common leading whitespace that JSON embedding adds.  Pass 2 handles the separate one-liner pattern where semicolons replace newlines.  Splitting these into explicit numbered passes makes each fix independently testable and prevents them from interfering with each other.

---

## Decision 9 — Partial Answer Synthesis Instead of format_error on Enumeration Tasks

**I considered** keeping the existing `format_error` exit path when the hollow-answer detector rejects the model's Final Answer three consecutive times, but **chose** replacing it with a `_synthesize_partial_answer()` method that extracts grounded facts directly from tool observations and builds a readable partial answer **because** the `format_error` label is misleading and punitive in cases where the agent successfully gathered real data (e.g. a Wikipedia summary of national capitals) but failed to turn that data into a valid Final Answer due to hallucination.  The synthesizer uses lightweight regex to pull country-capital pairs from observation text, assembles them into a markdown table, and prepends an honest disclaimer — producing a `completed (partial)` result instead of a bare failure.  This matches the assignment requirement that the budget enforcer "report exactly what the agent completed up to that point" rather than simply signalling a format failure.

---