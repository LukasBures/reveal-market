FROM golang:1.22-alpine AS builder

WORKDIR /app
COPY proover/go.mod ./
RUN go mod download
COPY proover/. .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /usr/bin/proover

FROM alpine:3.19

RUN apk add --no-cache nodejs npm bash wget curl ca-certificates && \
    npm install -g --unsafe-perm --loglevel=error rapidsnark@0.1.1 && \
    npm cache clean --force

RUN adduser -D -g '' prover
USER prover
WORKDIR /app

COPY proover/circuits /app/circuits
RUN mkdir -p /app/circuits/build
COPY --from=builder /usr/bin/proover /usr/local/bin/proover

ENV PROVER_LISTEN_ADDR=0.0.0.0:8085 \
    PROVER_CIRCUIT_DIR=/app/circuits/build \
    PROVER_WITNESS_SCRIPT=/app/circuits/build/settlement_js/generate_witness.js \
    PROVER_WASM_PATH=/app/circuits/build/settlement_js/settlement.wasm \
    PROVER_ZKEY_PATH=/app/circuits/build/settlement_final.zkey \
    PROVER_RAPIDSNARK_BINARY=rapidsnark

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://localhost:8085/healthz || exit 1

EXPOSE 8085
CMD ["/usr/local/bin/proover"]
