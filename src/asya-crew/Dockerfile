# Build the dlq-worker Go binary
FROM golang:1.25 AS dlq-builder
WORKDIR /build
COPY cmd/dlq-worker/go.mod cmd/dlq-worker/go.sum ./
RUN go mod download
COPY cmd/dlq-worker/ .
RUN CGO_ENABLED=0 GOOS=linux go build -o dlq-worker .

# Build the scaler-pubsub Go binary (KEDA external scaler)
FROM golang:1.25 AS scaler-builder
WORKDIR /build
COPY cmd/scaler-pubsub/go.mod cmd/scaler-pubsub/go.sum ./
RUN go mod download
COPY cmd/scaler-pubsub/ .
RUN CGO_ENABLED=0 GOOS=linux go build -o scaler-pubsub .

# TODO: good to test multiple Python versions 3.7+
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONPATH=/app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -q -r requirements.txt

# Copy crew code into ./asya_crew/ directory
COPY asya_crew/ asya_crew/

# Copy the dlq-worker binary (invoked via command override in Helm)
COPY --from=dlq-builder /build/dlq-worker /dlq-worker

# Copy the scaler-pubsub binary (invoked via command override in Helm)
COPY --from=scaler-builder /build/scaler-pubsub /scaler-pubsub
