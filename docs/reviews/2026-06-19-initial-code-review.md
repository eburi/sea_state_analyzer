# Initial code review — 2026-06-19

## Metadata

- **Review type:** initial code review
- **Scope:** repository-wide bootstrap review for harness adoption
- **Date:** 2026-06-19
- **Inputs reviewed:** `README.md`, `CLAUDE.md`, `inctructions.md`, `.github/workflows/ci.yml`, `.github/workflows/docker.yml`, `src/config.py`, `src/main.py`, `src/engine.py`, `src/feature_extractor.py`, `src/heave_estimator.py`, `sea_state_analyzer/config.yaml`, test surface under `tests/`

## Executive summary

The project already has a solid core architecture and unusually strong test breadth for a prototype in this stage. The main risks are not an obvious blocking correctness defect but **maintainability hotspots, CI/gate drift, and documentation/source drift**.

This repo is a good fit for a brownfield harness bootstrap: the code and tests are real enough to lead, but the operational guidance around them needed to be made explicit and agent-safe.

## Findings

### MEDIUM — Maintainability hotspot in large orchestrator and DSP modules

- **Source:** Maintainability
- **Paths:** `src/main.py`, `src/feature_extractor.py`, `src/heave_estimator.py`
- **Finding:** These modules are each over 1000 lines (`src/main.py` 1012, `src/feature_extractor.py` 1471, `src/heave_estimator.py` 1065). That size makes review, change isolation, and regression reasoning harder than necessary, especially in the hottest behavioral paths.
- **Verifiable:** yes — file size and future extraction slices are directly measurable.

### MEDIUM — CI is useful but still shallow relative to repo risk

- **Source:** Verification / workflow depth
- **Paths:** `.github/workflows/ci.yml`, `rust/`
- **Finding:** CI currently covers Ruff and pytest, but it does not yet express type checking, coverage thresholds, or Rust validation as routine gates. For a repo with optional acceleration, packaging, and large numerical modules, that leaves a meaningful gap between behavior risk and gate depth.
- **Verifiable:** yes — workflow contents are directly inspectable.

### MEDIUM — Documentation drift exists across primary project docs

- **Source:** Documentation consistency
- **Paths:** `README.md`, `CLAUDE.md`, `inctructions.md`
- **Finding:** The docs do not all describe the same current repo state. `inctructions.md` is both misspelled and legacy. `CLAUDE.md` remains useful but is not fully aligned with current code and packaging details. Without a harness, an agent could easily follow the wrong source.
- **Verifiable:** yes — cross-read of current docs shows conflicting and stale details.

### LOW — Local vs CI dependency drift around test tooling

- **Source:** Developer workflow parity
- **Paths:** `requirements-dev.txt`, `.github/workflows/ci.yml`
- **Finding:** CI installed `pytest-timeout` explicitly even though `requirements-dev.txt` did not. That makes local gate setup less faithful than it should be.
- **Verifiable:** yes — compare the requirements file with CI setup.

### LOW — Import/layout approach is intentional but fragile

- **Source:** Brownfield architecture constraints
- **Paths:** `conftest.py`, `src/`, top-level execution model
- **Finding:** The current script-style import approach is workable and clearly intentional, but it is easy for a well-meaning refactor to break. It should be treated as a constraint until a deliberate packaging migration is planned.
- **Verifiable:** yes — `conftest.py` explicitly injects `src/` into `sys.path`.

### INFO — Architecture decomposition is strong overall

- **Source:** Architecture / maintainability
- **Paths:** `src/config.py`, `src/signalk_client.py`, `src/state_store.py`, `src/sample_merge.py`, `src/engine.py`, `src/signalk_publisher.py`
- **Finding:** The repo already separates major responsibilities sensibly: config, ingestion, state merge, feature extraction, publishing, and optional Rust acceleration are distinct concepts in the codebase.
- **Verifiable:** partly — the module split is visible, though deeper architectural quality still depends on future review slices.

### INFO — Test breadth is a project strength

- **Source:** Quality posture
- **Paths:** `tests/test_*.py`
- **Finding:** The suite covers parsing, rolling windows, features, heave, engine behavior, authentication, publisher logic, IMU behavior, and vessel configuration. That breadth gives the repo a stronger starting point than many early-stage sensor/data projects.
- **Verifiable:** yes — test file surface is directly inspectable.

## Reviewed without concrete finding

- No concrete evidence was found in this pass of the project violating the self-vessel-only scope.
- No concrete evidence was found in this pass that the optional Rust engine had displaced Python as fallback/source of truth.
- The release-workflow direction of building/publishing from release tags rather than duplicating branch-plus-tag builds is the correct target behavior.
- No immediate evidence was found that local tests require live Signal K or IMU hardware by default.

## Recommended follow-up slices

1. Bootstrap the harness and make the source precedence explicit.
2. Converge local and CI gates on shared `make` targets.
3. Plan extraction slices for `src/main.py`, `src/feature_extractor.py`, and `src/heave_estimator.py`.
4. Decide whether to archive, remove, or explicitly mark `inctructions.md` as obsolete.
5. Add formal ADRs/spec artifacts only after the brownfield baseline has stabilized enough to make them truthful.

## Verdict

**Verdict:** mergeable with follow-up. The repo does not appear blocked by a single critical defect, but future work should treat maintainability hotspots and source drift as first-class risks rather than background noise.
