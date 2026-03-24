ARG BUILD_FROM

# ---- Builder stage: compile the Rust extension ---- #
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
RUN cd /tmp/rust \
    && maturin build --release \
    && mkdir -p /tmp/wheels \
    && cp target/wheels/*.whl /tmp/wheels/

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

# Install the pre-built Rust engine wheel from the builder stage
COPY --from=builder /tmp/wheels/ /tmp/wheels/
RUN pip3 install --no-cache-dir --break-system-packages /tmp/wheels/*.whl \
    && rm -rf /tmp/wheels

# Copy application source
COPY src/ /app/src/
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
