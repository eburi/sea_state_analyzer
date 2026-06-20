# Changelog

All notable changes to this project will be documented in this file.

## [1.2.3] - 2026-06-20

### Changed
- Make the Home Assistant add-on image treat the Rust extension as a best-effort optional build so newer base-image Python versions do not block releases.
- Use `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` when attempting the optional Rust wheel build inside the add-on image builder stage.
- Fall back to the Python engine automatically in the add-on image when no Rust wheel is produced.

### Notes
- The app/add-on version is bumped to `1.2.3` in `sea_state_analyzer/config.yaml`.
- The data/training version in `src/config.py` remains `0.3.0` because this release does not change the output schema.

## [1.2.2] - 2026-06-20

### Changed
- Bootstrap an agent-agnostic harness with canonical `AGENT.md`, `harness/README.md`, review/planning scaffolding, and a repo-specific reviewer skill.
- Align local and CI validation on shared `make` targets (`lint`, `format-check`, `test`, `gates`, `ci`).
- Update GitHub Actions usage and keep release-image publishing on pushed release tags only.
- Slim `CLAUDE.md` down to a legacy compatibility note and turn `inctructions.md` into an obsolete pointer to canonical docs.
- Make add-on image packaging tolerate optional Rust wheel build failures and continue with the Python engine fallback on newer base-image Python versions.

### Added
- Root `Makefile` for real local gate commands.
- `docs/reviews/2026-06-19-initial-code-review.md` as the initial review-first artifact.
- `docs/plan/` and `harness/` bootstrap structure for brownfield harness adoption.

### Notes
- The app/add-on version is bumped to `1.2.2` in `sea_state_analyzer/config.yaml`.
- The data/training version in `src/config.py` remains `0.3.0` because this release does not change the output schema.

## [1.2.1] - 2026-06-19

### Changed
- Fall back to Signal K `navigation.attitude` for roll/pitch/yaw when no local IMU is found.
- Keep local IMU channels overlaid only when a local IMU sample is actually available.
- Mirror the same attitude-fallback rule in the optional Rust-selected path.
- Add repeatable Docker-based Rust validation via `scripts/validate_rust_docker.sh`.

### Added
- `src/sample_merge.py` to centralize local IMU overlay and Signal K attitude fallback behavior.
- Rust helper and tests for the attitude-fallback decision.
- README documentation covering Signal K attitude fallback and Rust parity.

### Notes
- The app/add-on version is bumped to `1.2.1` in `sea_state_analyzer/config.yaml`.
- The data/training version in `src/config.py` remains `0.3.0` because this release does not change the output schema.
