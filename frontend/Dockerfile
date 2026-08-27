# ── Stage 1: Build ──
FROM node:22-alpine AS build
WORKDIR /app
ARG VITE_RELEASE_ID=dev
ARG VITE_SOURCE_COMMIT=unknown
ARG VITE_SOURCE_DIRTY=unknown
ARG VITE_BUILD_TIME=unknown
ARG VITE_DEPLOYMENT_MANIFEST_ID=unknown
ARG VITE_SCHEMA_HEAD=unknown
ENV VITE_RELEASE_ID=${VITE_RELEASE_ID} \
    VITE_SOURCE_COMMIT=${VITE_SOURCE_COMMIT} \
    VITE_SOURCE_DIRTY=${VITE_SOURCE_DIRTY} \
    VITE_BUILD_TIME=${VITE_BUILD_TIME} \
    VITE_DEPLOYMENT_MANIFEST_ID=${VITE_DEPLOYMENT_MANIFEST_ID} \
    VITE_SCHEMA_HEAD=${VITE_SCHEMA_HEAD}
LABEL org.opencontainers.image.revision=${VITE_SOURCE_COMMIT} \
      org.opencontainers.image.created=${VITE_BUILD_TIME} \
      io.enclave.release-id=${VITE_RELEASE_ID} \
      io.enclave.schema-head=${VITE_SCHEMA_HEAD}
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# ── Stage 2: Serve ──
FROM nginx:1.27-alpine

ARG VITE_RELEASE_ID=dev
ARG VITE_SOURCE_COMMIT=unknown
ARG VITE_BUILD_TIME=unknown
ARG VITE_SCHEMA_HEAD=unknown
LABEL org.opencontainers.image.revision=${VITE_SOURCE_COMMIT} \
      org.opencontainers.image.created=${VITE_BUILD_TIME} \
      io.enclave.release-id=${VITE_RELEASE_ID} \
      io.enclave.schema-head=${VITE_SCHEMA_HEAD}

# Remove default config
RUN rm -rf /usr/share/nginx/html/*

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Non-root user (nginx user already exists in nginx:alpine)
RUN chown -R nginx:nginx /usr/share/nginx/html \
    && chown -R nginx:nginx /var/cache/nginx \
    && chown -R nginx:nginx /var/log/nginx \
    && touch /var/run/nginx.pid \
    && chown -R nginx:nginx /var/run/nginx.pid

USER nginx

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
