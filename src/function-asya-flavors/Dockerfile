FROM golang:1.24 AS build

WORKDIR /fn
COPY go.mod go.sum ./
RUN go mod download

COPY *.go ./
RUN CGO_ENABLED=0 go build -o /function .

FROM gcr.io/distroless/static:nonroot
COPY --from=build /function /function
ENTRYPOINT ["/function"]
