ARG BUILD_FROM=ghcr.io/home-assistant/base:latest

# ---- Builder stage: best-effort compile of the optional Rust extension ---- #
FROM $BUILD_FROM AS builder

RUN apk add --no-cache \
        python3 \
        py3-pip \
        rust \
        cargo \
        build-base \
        musl-dev

RUN pip3 install --no-cache-dir --break-system-packages 'maturin[patchelf]'

COPY rust/ /tmp/rust/
RUN mkdir -p /tmp/wheels \
    && if cd /tmp/rust \
        && PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 maturin build --release \
        && cp target/wheels/*.whl /tmp/wheels/; then \
         echo "Rust extension wheel built successfully"; \
       else \
         echo "Rust extension build failed; continuing with Python fallback"; \
       fi

# ---- Runtime stage: lean final image ---- #
FROM $BUILD_FROM

# Runtime Python packages (no rust/cargo/build-base)
RUN apk add --no-cache \
        python3 \
        py3-pip \
        py3-numpy \
        py3-scipy \
        py3-pandas \
        py3-matplotlib \
        i2c-tools

# Install Python dependencies that aren't available as apk packages
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Install the pre-built Rust engine wheel when available.
# The Python engine remains the default and fallback if the optional Rust build
# is unavailable for the base image's Python/toolchain combination.
COPY --from=builder /tmp/wheels/ /tmp/wheels/
RUN if ls /tmp/wheels/*.whl >/dev/null 2>&1; then \
      pip3 install --no-cache-dir --break-system-packages /tmp/wheels/*.whl; \
    else \
      echo "No Rust wheel available; using Python engine fallback"; \
    fi \
    && rm -rf /tmp/wheels

# Copy application source
COPY src/ /app/src/
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
