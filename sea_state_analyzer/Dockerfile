ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-addon-base:latest
FROM $BUILD_FROM

# Install Python and build tools for native extensions (numpy, scipy)
RUN apk add --no-cache \
        python3 \
        py3-pip \
        py3-numpy \
        py3-scipy \
        py3-pandas \
        py3-matplotlib \
    && apk add --no-cache \
        i2c-tools

# Install Python dependencies that aren't available as apk packages
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Copy application source (populated by deploy script)
COPY src/ /app/src/
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

WORKDIR /app
CMD ["/app/run.sh"]
