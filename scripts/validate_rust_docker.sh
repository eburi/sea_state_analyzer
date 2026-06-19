#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

RUST_IMAGE=${RUST_DOCKER_IMAGE:-rust:1.89}
PYTHON_PACKAGES=${DOCKER_PYTHON_PACKAGES:-python3 python3-venv python3-pip}

printf '%s\n' '==> Rust Docker validation'
printf 'Repo: %s\n' "$REPO_ROOT"
printf 'Image: %s\n' "$RUST_IMAGE"

printf '\n%s\n' '==> cargo check'
docker run --rm \
  -v "$REPO_ROOT:/work" \
  -w /work \
  "$RUST_IMAGE" \
  cargo check --manifest-path rust/Cargo.toml

printf '\n%s\n' '==> cargo test'
docker run --rm \
  -v "$REPO_ROOT:/work" \
  -w /work \
  "$RUST_IMAGE" \
  cargo test --manifest-path rust/Cargo.toml

printf '\n%s\n' '==> maturin build'
docker run --rm \
  -e CARGO=/usr/local/cargo/bin/cargo \
  -v "$REPO_ROOT:/work" \
  -w /work \
  "$RUST_IMAGE" \
  sh -lc "
    export PATH=/tmp/maturin-venv/bin:/usr/local/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
    apt-get update
    apt-get install -y $PYTHON_PACKAGES
    python3 -m venv /tmp/maturin-venv
    /tmp/maturin-venv/bin/pip install maturin
    /tmp/maturin-venv/bin/maturin build --manifest-path rust/Cargo.toml --release
  "

printf '\n%s\n' '==> done'
printf 'Wheel output: %s\n' "$REPO_ROOT/rust/target/wheels"
