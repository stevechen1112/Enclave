# ── Stage 1: Build dependencies ──
FROM python:3.13-slim@sha256:7e3a6aca9d74f93cca21a91d86a8dad8c34749afd5b4a98ee481c9c47b9f5ed4 AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    python3-dev \
    libpq-dev \
    libxml2-dev \
    libxslt1-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Rust via rustup (needed for pydantic-core on ARM64 + Python 3.13)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:$PATH"

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir pip==26.2.1 && \
    pip install --no-cache-dir -r requirements.lock.txt

# ── Stage 2: Production image ──
FROM python:3.13-slim@sha256:7e3a6aca9d74f93cca21a91d86a8dad8c34749afd5b4a98ee481c9c47b9f5ed4

WORKDIR /code

# Install only runtime deps (no gcc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    openssl \
    tesseract-ocr \
    tesseract-ocr-chi-tra \
    ffmpeg \
    poppler-utils \
    libreoffice-writer \
    libreoffice-calc \
    libmagic1 \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Release identity changes on every build. Keep it after the expensive,
# content-stable OS dependency layer so immutable releases can reuse that cache.
ARG ENCLAVE_RELEASE_ID=dev
ARG ENCLAVE_SOURCE_COMMIT=unknown
ARG ENCLAVE_SOURCE_DIRTY=unknown
ARG ENCLAVE_BUILD_TIME=unknown
ARG ENCLAVE_DEPLOYMENT_MANIFEST_ID=unknown
ARG ENCLAVE_SCHEMA_HEAD=unknown
ARG ENCLAVE_ROUTE_CONTRACT_HASH=unknown
ENV ENCLAVE_RELEASE_ID=${ENCLAVE_RELEASE_ID} \
    ENCLAVE_SOURCE_COMMIT=${ENCLAVE_SOURCE_COMMIT} \
    ENCLAVE_SOURCE_DIRTY=${ENCLAVE_SOURCE_DIRTY} \
    ENCLAVE_BUILD_TIME=${ENCLAVE_BUILD_TIME} \
    ENCLAVE_DEPLOYMENT_MANIFEST_ID=${ENCLAVE_DEPLOYMENT_MANIFEST_ID} \
    ENCLAVE_SCHEMA_HEAD=${ENCLAVE_SCHEMA_HEAD} \
    ENCLAVE_ROUTE_CONTRACT_HASH=${ENCLAVE_ROUTE_CONTRACT_HASH}
LABEL org.opencontainers.image.revision=${ENCLAVE_SOURCE_COMMIT} \
      org.opencontainers.image.created=${ENCLAVE_BUILD_TIME} \
      io.enclave.release-id=${ENCLAVE_RELEASE_ID} \
      io.enclave.schema-head=${ENCLAVE_SCHEMA_HEAD}

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user
RUN groupadd -r enclave && useradd -r -g enclave -d /code -s /sbin/nologin enclave

COPY . .

RUN chown -R enclave:enclave /code
USER enclave

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
