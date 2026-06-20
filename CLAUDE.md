# CLAUDE.md — legacy compatibility notes

This file is kept only for tools that auto-load `CLAUDE.md`.

It is intentionally **minimal** so that project guidance stays DRY and canonical sources do not drift apart.

## Start here

If you are bootstrapping work in this repository, read these in order:

1. [`AGENT.md`](AGENT.md) — canonical agent briefing, source precedence, hard rules, local gates
2. [`harness/README.md`](harness/README.md) — harness entry point, sensors, workflow
3. latest relevant report under [`docs/reviews/`](docs/reviews/)
4. [`README.md`](README.md) — current project overview, architecture, usage, output schema, deployment notes

## What this file is for

Use this file only as a compatibility pointer plus a short set of non-obvious reminders for tool-specific sessions.

It is **not** the project contract, architecture spec, or primary operator documentation.

## Non-obvious reminders

- This repository is in **brownfield harness-bootstrap mode**: code, tests, and directly affected runtime/workflow files currently lead over prose docs.
- The current script-style `src/` layout and `conftest.py` path setup are intentional; do not casually rewrite the packaging/import model.
- The Python engine remains the source-of-truth fallback even when touching optional Rust acceleration.
- Versioning is split:
  - deployable app version: `sea_state_analyzer/config.yaml`
  - output/training semantics version: `src/config.py:VERSION`
- Tests and local gates should not require live Signal K or IMU hardware unless a command explicitly says so.

## Keep this file thin

If information already belongs in `AGENT.md`, `harness/README.md`, `README.md`, code, or tests, update those sources instead of expanding this file.
