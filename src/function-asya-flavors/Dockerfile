FROM golang:1.24 AS build

WORKDIR /fn
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

COPY *.go ./
RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 go build -o /function .

FROM gcr.io/distroless/static:nonroot
COPY --from=build /function /function
ENTRYPOINT ["/function"]
