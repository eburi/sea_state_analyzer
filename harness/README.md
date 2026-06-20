# Harness

This harness is the entry point for humans and coding agents working in `sea_state_analyzer`.

It connects the repo's real constraints, local gates, review artifacts, and planning notes. It is **not** a replacement for code, tests, or project docs.

## Purpose

This repository is currently in **brownfield harness-bootstrap mode**:

- the codebase is already substantial,
- tests exist and matter,
- docs are useful but partially drifted,
- formal `spec/` artifacts do not yet exist.

Because of that, this harness is intentionally honest about current maturity:

- **code and tests currently lead**,
- planning and ADR structure are bootstrapped here,
- review-first is mandatory for non-trivial work,
- gates reference only real `make` targets.

Repo-local adaptations to the course baseline are recorded in [`conventions.md`](conventions.md).

## Source precedence

| Rank | Source | Character |
|---|---|---|
| 1 | relevant code and tests in `src/`, `tests/`, and directly affected runtime files | current behavioral contract |
| 2 | [`docs/plan/adr/`](../docs/plan/adr/) | architecture decisions |
| 3 | [`docs/plan/planning/in-progress/roadmap.md`](../docs/plan/planning/in-progress/roadmap.md) | current planning direction |
| 4 | [`docs/reviews/`](../docs/reviews/) | review context and known risks |
| 5 | [`README.md`](../README.md) | project overview and operator-facing usage |
| 6 | [`CLAUDE.md`](../CLAUDE.md) | legacy compatibility notes for tools that auto-load it |
| 7 | [`AGENT.md`](../AGENT.md) | repo-wide agent briefing |
| 8 | this file | harness entry point |

## Guides

| Source | Purpose |
|---|---|
| [`AGENT.md`](../AGENT.md) | hard rules, workflow, local gates |
| [`harness/conventions.md`](conventions.md) | repo-specific adaptations to the adopted harness baseline |
| [`docs/reviews/2026-06-19-initial-code-review.md`](../docs/reviews/2026-06-19-initial-code-review.md) | initial code review and current hotspots |
| [`docs/plan/adr/README.md`](../docs/plan/adr/README.md) | ADR bootstrap and indexing rules |
| [`docs/plan/planning/README.md`](../docs/plan/planning/README.md) | planning artifact conventions |
| [`docs/plan/planning/in-progress/roadmap.md`](../docs/plan/planning/in-progress/roadmap.md) | active roadmap and likely next slices |
| [AI harness course, pinned baseline](https://github.com/pt9912/ai-harness-course/tree/d278c260cda0408dd3d2b7982b6c2752ce0cc152) | upstream baseline that informed this harness |
| [Pinned agents digest](https://raw.githubusercontent.com/pt9912/ai-harness-course/d278c260cda0408dd3d2b7982b6c2752ce0cc152/kurs/de/agents-regelwerk.md) | concise operating rules from the adopted baseline |
| [`.harness/skills/reviewer.md`](../.harness/skills/reviewer.md) | repo-specific reviewer checklist and classification guidance |

## Sensors

| Target | Contract | Binding |
|---|---|---|
| `make lint` | Python source and tests satisfy current Ruff lint rules | — |
| `make format-check` | Python source and tests satisfy current Ruff formatting rules | — |
| `make test` | Current pytest suite passes with timeout protection and no live-hardware requirement | — |
| `make gates` | Mandatory inner-gate bundle stays green before handoff | — |
| `make ci` | Local CI-equivalent gate bundle stays green | MR-005 |
| `make rust-validate` | Optional Rust extension surface remains build/test-able when the Rust toolchain is present | MR-005 |

Current GitHub workflow mapping:

- `.github/workflows/ci.yml` runs the same local gate commands through `make`.
- `.github/workflows/docker.yml` is reserved for add-on build/publish flow and should release only from pushed release tags.

## Traceability rules

- Until formal requirement IDs exist, reference **concrete files, sections, commands, and behaviors**.
- Do not invent requirement IDs.
- Use `MR-*` entries from [`conventions.md`](conventions.md) when pointing to harness-level adaptations.
- Once ADRs exist, use real four-digit `ADR-<NNNN>` references.
- Review reports are append-only: new review run, new file.

## Safety and scope boundaries

- Outputs are inferred motion and wave estimates; do not present them as authoritative measurements.
- Self-vessel scope is strict.
- Avoid changes that increase runtime coupling to live services or hardware for tests and local gates.
- Preserve Python fallback behavior when touching Rust acceleration.
- Do not relax a gate or workflow contract silently; document it in the harness first.

## Minimal agent workflow

1. Read this file and [`AGENT.md`](../AGENT.md).
2. Read the latest relevant report in [`docs/reviews/`](../docs/reviews/).
3. Read the relevant code/tests and any touched workflow or packaging files.
4. Plan the smallest safe change.
5. Implement.
6. Run the narrowest useful validation.
7. Run `make gates` before handoff when feasible.
8. Report executed sensors, findings, and remaining risks.
