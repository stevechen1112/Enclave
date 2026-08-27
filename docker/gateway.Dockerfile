FROM nginx:alpine@sha256:db35bfc6b2951e7f8a72db5db120288c127ffaeeb4a6d4b95a26fead017d5913

ARG ENCLAVE_RELEASE_ID=dev
ARG ENCLAVE_SOURCE_COMMIT=unknown
ARG ENCLAVE_BUILD_TIME=unknown

LABEL org.opencontainers.image.title="Enclave gateway" \
      org.opencontainers.image.version="${ENCLAVE_RELEASE_ID}" \
      org.opencontainers.image.revision="${ENCLAVE_SOURCE_COMMIT}" \
      org.opencontainers.image.created="${ENCLAVE_BUILD_TIME}"

# The stock image can lag fixed Alpine packages between nginx releases.
RUN apk upgrade --no-cache

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget --spider -q http://127.0.0.1:80/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
