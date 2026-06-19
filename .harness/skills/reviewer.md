# Reviewer skill — sea_state_analyzer

**Status:** bootstrap

**Scope:** repository reviews for code, docs, workflows, and harness artifacts

## Required context

Before reviewing a diff, read:

- the diff itself,
- `AGENT.md`,
- `harness/README.md`,
- `harness/conventions.md`,
- the latest relevant report under `docs/reviews/`,
- any directly affected code/tests/workflow/package files.

## Review priorities for this repo

Pay special attention to:

1. self-vessel-only scope,
2. ingest-path safety and async behavior,
3. output schema/semantic drift and versioning,
4. Python fallback preservation when Rust is touched,
5. workflow/release behavior,
6. doc drift against higher-precedence sources,
7. oversized-module blast radius.

## Classification

### HIGH

Use `HIGH` for findings that do any of the following:

- break self-vessel-only scope,
- introduce or require MQTT,
- make runtime behavior depend on `environment.wave.*`,
- risk blocking the ingest path with long synchronous work,
- silently change output meaning or required versioning behavior,
- remove or undermine Python fallback when Rust is involved,
- reintroduce duplicate release builds for branch-plus-tag pushes,
- introduce a security or correctness defect in an operator-facing path.

### MEDIUM

Use `MEDIUM` for findings that do any of the following:

- increase drift between code and agent/operator docs,
- change a hotspot module in a way that meaningfully increases complexity,
- add or change public behavior without adequate tests or validation,
- create local-vs-CI gate drift,
- introduce an avoidable architectural shortcut that is likely to become a recurring problem.

### LOW

Use `LOW` for findings that are worth fixing but are not merge blockers, such as:

- minor tooling inconsistency,
- localized maintainability nits,
- small doc clarity issues,
- one-off cleanup opportunities.

### INFO

Use `INFO` for contextual observations, strengths, or future follow-up ideas that do not require immediate action.

## What this reviewer does not do

- It does not rewrite the implementation.
- It does not demand broad refactors unrelated to the diff.
- It does not claim validation passed unless it has concrete evidence.
- It does not invent requirement IDs.

## Output schema

For each finding, report:

- `category`: `HIGH` | `MEDIUM` | `LOW` | `INFO`
- `source`: hard rule, workflow contract, maintainability, documentation consistency, or ADR/MR reference
- `path`: file or files involved
- `finding`: short observable statement
- `verifiable`: `yes`, `partly`, or `no`

Also include:

- a short executive summary,
- a `reviewed without concrete finding` section,
- a final verdict.
