---
tracker:
  kind: linear
  project_slug: "rover-2965f84dc454"
  active_states:
    - Planning
    - Todo
    - In Progress
  terminal_states:
    - Closed
    - Cancelled
    - Canceled
    - Duplicate
    - Done
polling:
  interval_ms: 30000
workspace:
  root: ~/code/rover-workspaces
hooks:
  after_create: |
    git clone --depth 1 https://github.com/michaelpersonal/openclaw-rover.git .
agent:
  max_concurrent_agents: 1
  max_turns: 10
planning:
  prompt_file: PLANNING.md
---

You are working on a Linear ticket `{{ issue.identifier }}` for the OpenClaw Rover project.

{% if attempt %}
Continuation context:

- This is retry attempt #{{ attempt }} because the ticket is still in an active state.
- Resume from the current workspace state instead of restarting from scratch.
{% endif %}

Issue context:
Identifier: {{ issue.identifier }}
Title: {{ issue.title }}
Current status: {{ issue.state }}
Labels: {{ issue.labels }}
URL: {{ issue.url }}

Description:
{% if issue.description %}
{{ issue.description }}
{% else %}
No description provided.
{% endif %}

## Project context

This is an AI-controlled 2WD rover. A Raspberry Pi Zero 2W runs an OpenClaw agent that interprets natural language commands and sends serial commands to an Arduino Nano, which drives two DC motors via a TB6612FNG motor driver.

Key files:
- `AI_HANDOFF.md` — full project context and architecture
- `docs/plans/` — design documents
- `arduino/rover/rover.ino` — Arduino firmware
- `simulator/rover_sim.py` — Python simulator with tests
- `openclaw-plugin/` — OpenClaw plugin (TypeScript)
- `monitor/rover_monitor.py` — telemetry TUI dashboard

## Instructions

1. Read `AI_HANDOFF.md` first to understand the full project context.
2. Work only in the provided repository copy.
3. Run existing tests before and after changes: `python3 -m pytest simulator/ -v` and `cd monitor && python3 -m pytest test_monitor.py -v`.
4. Follow existing code patterns and conventions.
5. When done, move the issue to `Human Review`.
