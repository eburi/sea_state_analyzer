# Changelog

All notable changes to this project will be documented in this file.

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
