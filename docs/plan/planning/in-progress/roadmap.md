# Roadmap

This roadmap is the current planning surface for the repository while the harness is being bootstrapped.

It is **directional**, not a replacement for code/tests as the current behavioral contract.

## Current priorities

### 1. Harness and workflow convergence

- keep `AGENT.md`, `harness/README.md`, and `harness/conventions.md` as the canonical agent-facing surface,
- keep local and CI validation aligned through shared `make` targets,
- continue replacing implicit tribal knowledge with explicit review and planning artifacts.

### 2. Documentation convergence

- keep `README.md` and harness docs canonical,
- keep `CLAUDE.md` and `inctructions.md` as thin compatibility pointers rather than parallel specs,
- ensure release/build workflow behavior is documented once, correctly.

### 3. Maintainability hotspot reduction

- extract coherent sub-components from `src/main.py`,
- split `src/feature_extractor.py` by layer or concern when a focused slice justifies it,
- split `src/heave_estimator.py` where algorithm families can be isolated without changing behavior.

### 4. Validation depth

- keep lint, format, and pytest green locally and in CI,
- later evaluate type checking, coverage policy, and Rust parity validation as explicit additional sensors,
- maintain the rule that tests should not need live Signal K or IMU hardware unless explicitly declared.

### 5. Product and algorithm roadmap already visible in repo docs/code

- derive STW-related behavior where the current pipeline still relies on fallbacks,
- continue Doppler and heave estimation refinement,
- improve wave partitioning and confidence reporting,
- preserve Home Assistant add-on portability while keeping macOS and Raspberry Pi development viable.

## Likely next slices

1. Keep workflow and harness docs in sync after release/build changes.
2. Introduce the first ADRs once recurring decisions are stable enough to record truthfully.
3. Take a focused extraction slice on one of the three oversized modules.
4. Decide whether to add a type-checking or coverage gate after a narrow trial rather than a repo-wide mandate.

## Out of scope for bootstrap

- inventing a full requirement ID system before the repo is ready,
- broad packaging rewrites,
- making Rust mandatory,
- expanding the product to other-vessel data or MQTT.
