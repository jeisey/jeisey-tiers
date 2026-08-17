@AGENTS.md

# Claude Code bridge

`AGENTS.md` is the canonical repository contract. Follow it in full.

Claude-specific notes:

- For large or ambiguous changes, begin in planning mode and inspect the code/tests before editing.
- Use subagents/dynamic workflows only for independent workstreams with non-overlapping ownership; the main agent must reproduce and validate the integrated result.
- Keep durable state in `TASKS.md`, `SESSION_STATE.md`, ADRs, tests, and model cards rather than relying on conversation memory.
- If a future Claude model is selected, do not assume its context, effort, or tool behavior from this file; use the active Claude Code capabilities while preserving the repository contract.
