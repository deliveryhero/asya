FROM debian:bookworm-slim

ARG TARGETARCH
ARG VERSION=latest

RUN apt-get update && apt-get install -y curl ca-certificates && rm -rf /var/lib/apt/lists/*

# Download VidaiMock binary based on architecture
RUN case "${TARGETARCH}" in \
        amd64) ARCH="linux-x64" ;; \
        arm64) ARCH="linux-arm64" ;; \
        *) echo "Unsupported arch: ${TARGETARCH}" && exit 1 ;; \
    esac && \
    curl -L "https://github.com/vidaiUK/VidaiMock/releases/${VERSION}/download/vidaimock-${ARCH}.tar.gz" \
        -o /tmp/vidaimock.tar.gz && \
    tar -xzf /tmp/vidaimock.tar.gz -C /opt && \
    rm /tmp/vidaimock.tar.gz && \
    chmod +x /opt/vidaimock/vidaimock

WORKDIR /opt/vidaimock

EXPOSE 8100

ENTRYPOINT ["/opt/vidaimock/vidaimock"]
CMD ["--host", "0.0.0.0", "--port", "8100"]
