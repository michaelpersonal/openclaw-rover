# Symphony Orchestrator Design

Date: 2026-03-07
Linear Issue: MIC-9

## Overview

A lightweight Symphony orchestrator in Node.js/TypeScript that polls Linear for issues and runs Claude Code sessions autonomously. It reads config from the existing `WORKFLOW.md`, creates isolated git worktrees per issue, and streams Claude Code output to track progress.

## Architecture

Single long-running Node.js process with three layers:

1. **Poller** — Queries Linear GraphQL API on a fixed interval for issues in active states (Todo, In Progress) within the configured project. Compares against in-memory claimed set to avoid duplicate dispatch.
2. **Worker Manager** — Spawns Claude Code subprocesses (`claude --print --output-format stream-json --dangerously-skip-permissions`). One per issue, bounded by `max_concurrent_agents`. Parses streaming JSON output for progress.
3. **Linear Reporter** — Manages a single "Symphony Workpad" comment per issue. Posts start/progress/completion updates. Moves issue states. Links PRs.

```
┌─────────────────────────────────────────┐
│            Symphony (Node.js)           │
│                                         │
│  ┌──────────┐  ┌──────────┐  ┌───────┐ │
│  │  Poller  │→ │  Worker  │→ │Linear │ │
│  │ (Linear) │  │  Manager │  │Reporter│ │
│  └──────────┘  └──────────┘  └───────┘ │
│                     │                   │
│            ┌────────┼────────┐          │
│            ▼        ▼        ▼          │
│        claude    claude    claude        │
│        --print   --print   --print      │
│        (worktree)(worktree)(worktree)   │
└─────────────────────────────────────────┘
```

## Worker Lifecycle

1. **Claim & State Transition** — Add issue to claimed set. Move Todo → In Progress. Create/find workpad comment.
2. **Workspace Setup** — `git worktree add <root>/<MIC-XX> -b symphony/<MIC-XX>` branching off main.
3. **Launch Claude Code** — Run `claude --print --output-format stream-json --dangerously-skip-permissions -p "<prompt>"` in the worktree directory.
4. **Stream Processing** — Parse JSON events. Log tool calls and assistant messages. Post debounced updates to workpad comment (max once per 60s).
5. **Completion** — Agent commits, pushes, creates PR via `gh`. Orchestrator extracts PR URL, posts final summary, links PR on issue, moves to Human Review.
6. **Failure** — On non-zero exit or timeout, post error to workpad, leave issue In Progress.

## Project Structure

```
symphony/
  package.json
  tsconfig.json
  src/
    index.ts          # Entry point, poll loop, CLI args
    config.ts         # Parse WORKFLOW.md front matter + env resolution
    poller.ts         # Linear GraphQL client, fetch eligible issues
    worker.ts         # Spawn claude subprocess, stream parsing
    reporter.ts       # Linear comment management, state transitions
    types.ts          # Shared interfaces
```

## Dependencies

- `yaml` — Parse WORKFLOW.md front matter
- Node built-ins only: `child_process`, `fs`, `path`, `readline`
- No framework, no database

## Config

Read from `WORKFLOW.md` at repo root:
- `tracker.project_slug` — Linear project to poll
- `tracker.active_states` — States to pick up (Todo, In Progress)
- `tracker.terminal_states` — States that mean done
- `polling.interval_ms` — Poll interval (default 30s)
- `workspace.root` — Where to create worktrees
- `agent.max_concurrent_agents` — Concurrency cap

Environment: `LINEAR_API_KEY` required.

## Stream Parsing & Reporting

Claude Code `stream-json` emits one JSON object per line with types: `assistant`, `tool_use`, `tool_result`.

Workpad comment format:

```markdown
## Symphony Workpad

\```text
<workspace-root>/MIC-XX@<short-sha>
\```

### Status: In Progress

### Activity
- [HH:MM:SS] Agent started
- [HH:MM:SS] Reading project context
- [HH:MM:SS] Editing src/foo.ts
- [HH:MM:SS] Running tests
- [HH:MM:SS] Created PR #N

### Result
PR: <url>
Commits: N files changed
```

Reporting rules:
- Create workpad on agent start
- Debounce updates to once per 60 seconds
- Log tool_use as one-liners (e.g., "Editing src/foo.ts")
- On completion: final summary + PR link, move to Human Review
- On failure: error in workpad, leave In Progress

## Running

```bash
cd symphony && npm install && npm start
# Custom workflow path:
npm start -- --workflow ../WORKFLOW.md
```
