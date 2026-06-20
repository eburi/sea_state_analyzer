# AGENT.md — agent-agnostic repo briefing

This is the canonical onboarding brief for any coding agent working in this repository.

It is intentionally **agent-agnostic**. `AGENTS.md` exists only as a compatibility shim for tools that auto-load that filename. `CLAUDE.md` remains a thin legacy compatibility note for tools that auto-load it, but it is no longer the canonical harness entry point.

This repo adopts the AI harness course approach from `pt9912/ai-harness-course`, pinned in `harness/conventions.md` to a concrete upstream revision.

## 1. What this file is

Use this file to bootstrap every work session before changing code, docs, workflows, or packaging.

This file carries:

- hard rules that apply repo-wide,
- source precedence for this brownfield codebase,
- the real local quality gates,
- a minimal workflow for planning, review, implementation, and verification.

This file does **not** duplicate full project context. Follow the pointers below instead of improvising.

## 2. Canonical sources and precedence

This repository is currently in **brownfield harness-bootstrap mode**. There is not yet a formal `spec/` tree, so the current behavioral contract is led by code, tests, and runtime packaging.

When sources disagree, use this order:

1. The **relevant code and tests** under `src/`, `tests/`, and any directly affected runtime files such as `sea_state_analyzer/config.yaml`, `.github/workflows/*.yml`, and `requirements*.txt`.
2. `docs/plan/adr/`.
3. `docs/plan/planning/in-progress/roadmap.md`.
4. `docs/reviews/` — advisory, but required context for non-trivial work; start with the latest report.
5. `README.md`.
6. `CLAUDE.md` — legacy compatibility notes for tools that auto-load it; intentionally minimal and non-canonical.
7. `AGENT.md`.
8. `harness/README.md`.

If you discover drift, fix it or report it explicitly. Do not silently pick the convenient source.

## 3. Hard rules

### 3.1 Domain and scope

- This project ingests **self-vessel data only**.
- Do **not** expand scope to other vessels.
- Do **not** introduce MQTT.
- Do **not** make the system depend on `environment.wave.*` being present.
- Treat outputs as **inferred sea-state estimates**, not authoritative wave-buoy measurements.

### 3.2 Runtime and architecture

- Python 3.11+ and `asyncio` are the default implementation model.
- Never block the ingest path with long synchronous work.
- Preserve bounded queues and fixed-length rolling buffers.
- Keep the Python engine as the source-of-truth fallback even when touching Rust acceleration.
- Do not casually rewrite the repo into a different packaging/import model; the current script-style layout and `conftest.py` path setup are intentional brownfield constraints.

### 3.3 Data contracts

- Internal units stay in **radians** and **m/s** unless a file already documents a display/export exception.
- All timestamps must be timezone-aware UTC `datetime` values.
- Do not silently change output field meaning, scale, or schema.
- If a change affects recorded/output semantics, follow the versioning rules:
  - bump app version in `sea_state_analyzer/config.yaml` for deployable app changes,
  - bump `src/config.py:VERSION` for output/training schema or feature-semantics changes.

### 3.4 Change discipline

- Prefer the smallest change that fixes the actual problem.
- Do not do broad refactors unless explicitly requested or required to complete the task safely.
- Keep docs, tests, and workflows in sync when public behavior or developer workflow changes.
- Do not invent gates, commands, requirements, or architecture constraints that do not exist.
- Do not claim validation passed unless you actually ran it.

### 3.5 Review-first rule

For any non-trivial change:

1. read `harness/README.md`,
2. read the latest report in `docs/reviews/`,
3. decide whether the planned change touches an existing hotspot or drift area,
4. then implement.

If the change is substantial, add a new review report or update the relevant planning artifact rather than relying on chat history.

## 4. Quality gates

These are the real local gates. If a command is listed here, it must exist in `Makefile`.

| Target | Purpose |
|---|---|
| `make lint` | Ruff lint on `src/` and `tests/` |
| `make format-check` | Ruff formatting check on `src/` and `tests/` |
| `make test` | pytest suite with timeout protection |
| `make gates` | mandatory local gate bundle |
| `make ci` | current CI-equivalent local gate bundle |
| `make rust-validate` | optional Rust engine validation surface |

## 5. Documentation and traceability rules

- Until a formal spec/ID system exists, do **not** invent requirement IDs.
- Reference concrete files, sections, commands, and behaviors instead.
- Use `MR-*` IDs from `harness/conventions.md` and `ADR-*` IDs once real ADRs exist.
- Keep review reports append-only: new run, new file.
- `CLAUDE.md` should stay thin. Do not duplicate guidance there that belongs in `AGENT.md`, `harness/README.md`, `README.md`, code, or tests.

## 6. Minimal agent workflow

For each non-trivial slice:

1. Read `AGENT.md` and `harness/README.md`.
2. Read the latest relevant review report in `docs/reviews/`.
3. Read the most relevant code/tests and any touched workflow or packaging files.
4. State the smallest safe plan before editing.
5. Make the change.
6. Run the narrowest useful validation first.
7. Run `make gates` before handoff when feasible.
8. Report what changed, what was validated, and any remaining risks or drift.

## 7. Repo-specific common-sense reminders

- Sensor availability is not guaranteed; code must tolerate missing or malformed data.
- Tests and local tooling should not require live Signal K or IMU hardware unless a command explicitly says so.
- Release automation should publish on release tags, not duplicate work for both branch and tag pushes of the same commit.
- Portability matters: prefer solutions that work on macOS and Raspberry Pi Linux with minimal divergence.
- When in doubt, preserve observability and fallback behavior over cleverness.
