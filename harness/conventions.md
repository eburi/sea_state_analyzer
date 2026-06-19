# Harness conventions

## Purpose

This file records the repo-local adaptations for the harness adopted in `sea_state_analyzer`.

It is the place for:

- baseline declaration,
- source-precedence adaptations,
- brownfield vs greenfield mode declarations,
- local rules that differ from the upstream course baseline.

When this file conflicts with a higher-precedence source, the higher-precedence source wins.

## Baseline

- **Convention:** AI Harness Course (`pt9912/ai-harness-course`)
- **Pinned upstream revision:** `d278c260cda0408dd3d2b7982b6c2752ce0cc152`
- **Upstream date:** `2026-06-18`
- **Adoption date:** `2026-06-20`

## Adopted convention sources

- **Course repo:** <https://github.com/pt9912/ai-harness-course/tree/d278c260cda0408dd3d2b7982b6c2752ce0cc152>
- **Pinned agents digest:** <https://raw.githubusercontent.com/pt9912/ai-harness-course/d278c260cda0408dd3d2b7982b6c2752ce0cc152/kurs/de/agents-regelwerk.md>
- **Pinned template roots:**
  - <https://raw.githubusercontent.com/pt9912/ai-harness-course/d278c260cda0408dd3d2b7982b6c2752ce0cc152/lab/templates/AGENTS.template.md>
  - <https://raw.githubusercontent.com/pt9912/ai-harness-course/d278c260cda0408dd3d2b7982b6c2752ce0cc152/lab/templates/harness/README.template.md>
  - <https://raw.githubusercontent.com/pt9912/ai-harness-course/d278c260cda0408dd3d2b7982b6c2752ce0cc152/lab/templates/harness/conventions.template.md>
- **In-repo embodiment:** `AGENT.md`, `AGENTS.md`, `harness/README.md`, `docs/reviews/`, `docs/plan/`, `.harness/skills/reviewer.md`

## Adaptation block

### MR-000 — Baseline adoption

- **Date:** 2026-06-20
- **Scope:** entire repository
- **Adaptation:** adopt the course baseline as the default harness model for review, planning, verification, and quality gates.
- **Reason:** establish a reproducible, reviewable, agent-agnostic operating model for an already-active brownfield codebase.
- **Resolution trigger:** permanent.

### MR-001 — Canonical root briefing uses `AGENT.md`

- **Date:** 2026-06-20
- **Scope:** repository root agent briefing
- **Adaptation:** `AGENT.md` is the canonical briefing file; `AGENTS.md` is a compatibility shim that points back to it.
- **Reason:** this repo wants an agent-agnostic root briefing while still supporting tools that auto-load `AGENTS.md`.
- **Resolution trigger:** permanent.

### MR-002 — Brownfield source precedence

- **Date:** 2026-06-20
- **Scope:** `AGENT.md`, `harness/README.md`
- **Adaptation:** relevant code, tests, runtime packaging, and workflow files outrank docs until a formal spec tree exists.
- **Reason:** current repo reality is code-led and some docs already drift; pretending a non-existent `spec/` layer is authoritative would be a harness lie.
- **Resolution trigger:** revisit when a reviewed `spec/` tree exists and is adopted as the new top contract.

### MR-003 — No invented requirement IDs during bootstrap

- **Date:** 2026-06-20
- **Scope:** planning, review, commit/PR traceability
- **Adaptation:** until a formal requirement spec exists, agents must reference concrete files, sections, commands, and behaviors rather than inventing requirement IDs.
- **Reason:** the course expects formal IDs, but this repo is not there yet; invented IDs would create fake traceability.
- **Resolution trigger:** replace when formal requirement IDs are introduced.

### MR-004 — Review-first bootstrap rule

- **Date:** 2026-06-20
- **Scope:** non-trivial code, workflow, and tooling changes
- **Adaptation:** agents must read the latest review report before non-trivial work; significant new work should add a new report rather than relying on transient chat context.
- **Reason:** the codebase already has known maintainability and documentation hotspots that should shape implementation choices.
- **Resolution trigger:** permanent.

### MR-005 — Mandatory vs optional sensors

- **Date:** 2026-06-20
- **Scope:** `Makefile`, `harness/README.md`, `.github/workflows/ci.yml`
- **Adaptation:** `lint`, `format-check`, `test`, `gates`, and `ci` are mandatory local sensors; `rust-validate` exists but is not part of `make gates` because the Rust engine is optional and host toolchains may be absent.
- **Reason:** keeps the mandatory gate surface real and reproducible while still exposing Rust validation when available.
- **Resolution trigger:** revisit if Rust becomes mandatory for default operation or CI parity requires it.

## Additional sensor classes

— none —

## Mode declaration by sub-area

| Sub-area | Mode | Reason | Graduation condition / follow-up |
|---|---|---|---|
| `src/` | Brownfield | substantial existing implementation and tests already lead | converge toward smaller modules and explicit ADR/spec coverage over time |
| `tests/` | Brownfield | existing suite is already meaningful and part of the behavioral contract | formalize critical-path coverage and verification criteria later |
| `.github/workflows/` | Brownfield | release and CI behavior already exist and affect delivery | document and tighten as workflow contracts stabilize |
| `harness/` | Greenfield | newly bootstrapped harness surface | n/a |
| `docs/plan/` | Greenfield | planning/ADR structure is newly bootstrapped | n/a |
| `docs/reviews/` | Greenfield | review archive starts with initial report | n/a |
| `CLAUDE.md` | Hybrid | valuable detailed context, but currently partly legacy/drift-prone | keep aligned or progressively deprecate in favor of harness docs |

## Glossary

| Term | Meaning in this repo |
|---|---|
| brownfield harness-bootstrap | course-style harness added after the codebase already exists |
| self-vessel scope | only `vessels.self` data and related local device data are in scope |
| inferred sea-state output | wave or motion result estimated from vessel motion, not direct environmental measurement |
