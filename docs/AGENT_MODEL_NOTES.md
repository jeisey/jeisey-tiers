# Frontier Coding-Agent Notes (researched 2026-08-17)

This file explains why the repository handoff is structured the way it is. It is not a requirement to use a specific model vendor.

## 1. GPT-5.6 Sol

OpenAI's current official documentation describes GPT-5.6 Sol as its flagship/frontier model for complex professional work, including coding and long-horizon agentic workflows.

Relevant capabilities at research time:

- model ID / alias: `gpt-5.6-sol` / `gpt-5.6`;
- 1,050,000-token context window;
- up to 128,000 output tokens in the API;
- reasoning levels including `none`, `low`, `medium`, `high`, `xhigh`, and `max` in current model docs;
- tool support includes function calling, web/file search, code interpreter/hosted shell, apply patch, computer use, MCP, and skills depending harness;
- OpenAI describes Sol as its strongest coding model and reports strong performance on Terminal-Bench/DeepSWE-style long-horizon engineering;
- current ChatGPT/Codex experiences may expose multi-agent/`ultra` capabilities depending plan/product.

### Implication for this repo

A Sol-class agent can ingest most/all of this specification and a substantial codebase, but the repo should still externalize state because:

- long sessions accumulate tool output/noise;
- multiple sessions/agents need consistent instructions;
- prompt caching/context efficiency improves when canonical guidance is stable;
- tests and durable docs are stronger than relying on model memory.

`AGENTS.md` is intentionally compact enough to be globally useful while specialized details live in phase docs.

## 2. OpenAI Codex / AGENTS.md

OpenAI documents `AGENTS.md` as a way to guide Codex within a repository, including navigation, test commands, conventions, and scoped instructions. Codex supports parallel agent workflows in current products.

### Implication

- keep `AGENTS.md` at repo root;
- put critical commands/invariants there;
- use nested `AGENTS.md` only if future subtrees truly need different rules;
- let parallel agents own independent worktrees/files, then integrate/test centrally.

## 3. Claude / Opus 5 status

**Claude Opus 5 is a released, current Anthropic model.** Anthropic launched it on **July 24, 2026** for complex agentic coding and enterprise work. The Claude API model ID is `claude-opus-5`.

Relevant capabilities at research time:

- **1,000,000-token context window**; 1M is both the default and maximum context size;
- **128,000 max output tokens**;
- **thinking is on by default**;
- Anthropic positions Opus 5 for complex agentic coding, deep reasoning, and long-horizon tasks;
- current platform guidance highlights stronger instruction following, tool use across long contexts, and multi-agent coordination;
- **mid-conversation tool changes** are supported in beta, allowing tools to be added or removed while preserving prompt-cache continuity;
- available through the Claude API and major cloud platforms including Amazon Bedrock, Google Cloud, and Microsoft Foundry.

Anthropic's Opus 5 prompting guidance says existing Opus 4.8 prompts generally transfer well, while recommending explicit task scoping and careful subagent delegation for long-running work.

### Claude Code capabilities relevant to the handoff

Claude Code is a terminal coding agent that can inspect, edit, and run code; supports model selection, planning/permission modes, MCP, subagents, and project memory via `CLAUDE.md`.

### Implication for this repo

`CLAUDE.md` imports `AGENTS.md`, making the same repository contract available to Claude Code without maintaining a second divergent instruction manual.

Opus 5's large context and agentic strengths make it suitable for whole-repository orientation and substantial bounded milestones, but the project should still externalize durable state in `TASKS.md`, `SESSION_STATE.md`, tests, ADRs, and model cards. Do not rely on a single long conversation as the source of truth.

## 4. Recommended reasoning-mode allocation

Regardless of vendor, use the strongest available reasoning mode selectively for:

- Phase-0 source/terms research;
- architecture changes/ADRs;
- temporal leakage analysis;
- feature/target design;
- model evaluation/promotion decisions;
- complex identity bugs;
- GitHub Actions concurrency/permission issues;
- hard UI/chart geometry/accessibility bugs.

Lower effort is appropriate for deterministic implementation once interfaces/tests are established.

The goal is not to force maximal reasoning on every file edit; it is to spend intelligence where wrong assumptions would propagate through the project.

## 5. Recommended multi-agent decomposition

If harness supports subagents/worktrees:

### Phase 0

- Agent A: nflverse/ffopportunity feasibility + license
- Agent B: MFL ADP history + schema
- Agent C: Sleeper/FantasyCalc/terms
- Lead: synthesize source policy and reproduce key probes

### Modeling phases

- Agent A: historical feature/data quality
- Agent B: baseline/eval harness
- Agent C: leakage reviewer (prefer read-only independent critic)
- Lead: integrate/final experiment

### Frontend

- Agent A: artifact loader/state/table
- Agent B: Tier Board on frozen fixture
- Agent C: Draft Rail on frozen fixture
- Lead: unify design/state/accessibility and run E2E

### Release QA

Use an independent critic agent to inspect:

- forbidden intrinsic features
- leakage
- source terms/attribution
- workflow permissions
- chart/table consistency

## 6. Context-management rules

For long-horizon agents:

- summarize durable decisions into `SESSION_STATE.md` after each phase;
- store experiment metrics under version control/artifacts, not only chat;
- prefer referencing stable docs over pasting the same spec repeatedly;
- after major phase completion, start a fresh session if accumulated context is noisy;
- fresh agent should be able to resume from repo alone.

That last point is a core quality test of this handoff bundle.

## 7. Sources used for these notes

Research date: 2026-08-17.

- OpenAI GPT-5.6 Sol model documentation: https://developers.openai.com/api/docs/models/gpt-5.6-sol
- OpenAI GPT-5.6 launch/model guidance: https://openai.com/index/gpt-5-6/ and https://developers.openai.com/api/docs/guides/latest-model
- OpenAI Codex overview / AGENTS.md guidance: https://openai.com/codex/ and https://openai.com/index/introducing-codex/
- Anthropic Claude Opus 5 platform guide: https://platform.claude.com/docs/en/about-claude/models/whats-new-opus-5
- Anthropic Claude Opus 5 prompting guide: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5
- Anthropic Claude release notes (Opus 5 launch, July 24, 2026): https://support.claude.com/en/articles/12138966-release-notes
- Claude Code docs: https://docs.anthropic.com/en/docs/claude-code/getting-started

Re-check official docs when a materially newer agent/model is used.
