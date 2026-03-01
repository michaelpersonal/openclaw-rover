# Brain Domain (OpenClaw)

## What is OpenClaw
- Open-source self-hosted AI agent (formerly Moltbot/Clawdbot)
- Runs on Raspberry Pi Zero 2 W
- Skill/plugin system for extending capabilities
- Supports MCP, multiple LLM providers, local models via Ollama

## Rover Skill
- TypeScript skill registered with OpenClaw
- Exposes 8 tools: rover_forward, rover_backward, rover_left, rover_right, rover_spin_left, rover_spin_right, rover_stop, rover_status
- Each tool sends a serial command and returns the response
- Configurable serial port path (real hardware or simulator)
- Includes system prompt snippet explaining rover capabilities to the LLM

## AI Reasoning Chain
```
User intent ("go forward slowly")
  → LLM reasons about speed semantics (slowly ≈ 80)
  → LLM calls rover_forward(speed=80)
  → Skill sends "FORWARD 80\n" over serial
  → Arduino/Simulator responds "OK\n"
  → Skill returns success to LLM
  → LLM responds to user
```

## Speed Semantics (for LLM system prompt)
- 0 = stopped
- ~80 = slow
- ~150 = medium
- ~200 = fast
- 255 = maximum
