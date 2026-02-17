# syntax=docker/dockerfile:1.4

ARG BUILDKIT_INLINE_CACHE=1
ARG APK_REPO_URL=https://dl-cdn.alpinelinux.org/alpine
ARG GOLANG_IMAGE=golang:1.24-alpine
ARG NODE_IMAGE=node:20-alpine
ARG DEBIAN_IMAGE=debian:bookworm-slim

FROM ${GOLANG_IMAGE} AS builder
ARG APK_REPO_URL

WORKDIR /app
COPY prover/go.mod ./
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go mod download
COPY prover/. .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /usr/bin/prover

FROM ${DEBIAN_IMAGE} AS rapidsnark

ARG RAPIDSNARK_VERSION=v0.0.7
ARG TARGETARCH

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends ca-certificates curl unzip && \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    mkdir -p /opt/rapidsnark; \
    case "${TARGETARCH}" in \
      "amd64") RAPIDSNARK_ARCHIVE="rapidsnark-linux-x86_64-${RAPIDSNARK_VERSION}.zip" ;; \
      "arm64") RAPIDSNARK_ARCHIVE="rapidsnark-linux-arm64-${RAPIDSNARK_VERSION}.zip" ;; \
      *) echo "unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/rapidsnark.zip "https://github.com/iden3/rapidsnark/releases/download/${RAPIDSNARK_VERSION}/${RAPIDSNARK_ARCHIVE}"; \
    unzip /tmp/rapidsnark.zip -d /tmp/rapidsnark; \
    cp -r /tmp/rapidsnark/rapidsnark-linux-*-${RAPIDSNARK_VERSION}/. /opt/rapidsnark; \
    rm -rf /tmp/rapidsnark /tmp/rapidsnark.zip

FROM ${NODE_IMAGE}

ARG APK_REPO_URL

RUN --mount=type=cache,target=/var/cache/apk set -eux; \
    ALPINE_VERSION="$(cut -d. -f1,2 /etc/alpine-release)"; \
    echo "${APK_REPO_URL}/v${ALPINE_VERSION}/main" > /etc/apk/repositories; \
    echo "${APK_REPO_URL}/v${ALPINE_VERSION}/community" >> /etc/apk/repositories; \
    apk add --no-cache ca-certificates curl wget gcompat libstdc++

RUN adduser -D -H -s /sbin/nologin prover
WORKDIR /app

COPY prover/circuits /app/circuits
RUN mkdir -p /app/circuits/build
COPY --from=builder /usr/bin/prover /usr/local/bin/prover
COPY --from=rapidsnark /opt/rapidsnark /opt/rapidsnark
RUN ln -sf /opt/rapidsnark/bin/prover /usr/local/bin/rapidsnark && \
    chown -R prover:prover /app /opt/rapidsnark

USER prover

ENV PROVER_LISTEN_ADDR=0.0.0.0:8085 \
    PROVER_CIRCUIT_DIR=/app/circuits/build \
    PROVER_WITNESS_SCRIPT=/app/circuits/build/settlement_js/generate_witness.js \
    PROVER_WASM_PATH=/app/circuits/build/settlement_js/settlement.wasm \
    PROVER_ZKEY_PATH=/app/circuits/build/settlement_final.zkey \
    PROVER_RAPIDSNARK_BINARY=rapidsnark \
    PROVER_LOG_LEVEL=INFO \
    LD_LIBRARY_PATH=/opt/rapidsnark/lib:${LD_LIBRARY_PATH:-}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://localhost:8085/healthz || exit 1

EXPOSE 8085
CMD ["/usr/local/bin/prover"]
