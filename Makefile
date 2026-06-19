PYTHON ?= python3
RUFF ?= ruff
PYTEST ?= pytest

.PHONY: help lint format-check test gates ci rust-validate

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "; printf "Available targets:\n"} /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-15s %s\n", $$1, $$2}' Makefile

lint: ## Ruff lint on src/ and tests/
	$(RUFF) check src/ tests/

format-check: ## Ruff formatting check on src/ and tests/
	$(RUFF) format --check src/ tests/

test: ## pytest suite with timeout protection
	$(PYTEST) tests/ -v --timeout=30

gates: lint format-check test ## Mandatory local gate bundle

ci: gates ## Current CI-equivalent local gate bundle

rust-validate: ## Optional Rust validation surface
	@if command -v cargo >/dev/null 2>&1; then \
		cargo test --manifest-path rust/Cargo.toml; \
	else \
		echo "cargo not found; skipping rust tests"; \
	fi
	@if $(PYTHON) -m pip show maturin >/dev/null 2>&1; then \
		$(PYTHON) -m maturin build --manifest-path rust/Cargo.toml; \
	else \
		echo "maturin not installed; skipping Rust wheel build"; \
	fi
