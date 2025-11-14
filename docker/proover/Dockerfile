FROM golang:1.22-alpine AS builder

WORKDIR /app
COPY proover/go.mod ./
RUN go mod download
COPY proover/. .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /usr/bin/proover

FROM alpine:3.19
RUN adduser -D -g '' prover
USER prover
WORKDIR /app
COPY --from=builder /usr/bin/proover /usr/local/bin/proover
EXPOSE 8085
ENV PROVER_LISTEN_ADDR=0.0.0.0:8085
CMD ["/usr/local/bin/proover"]
