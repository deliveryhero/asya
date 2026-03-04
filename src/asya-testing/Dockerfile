FROM python:3.13-slim

WORKDIR /opt/asya

# Install CLI tools used by Helm tests (curl, wget, jq)
# and kubectl for Kubernetes resource inspection
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl wget jq \
    && ARCH=$(dpkg --print-architecture) \
    && curl -fsSL "https://dl.k8s.io/release/v1.28.3/bin/linux/${ARCH}/kubectl" -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml requirements.txt ./
COPY asya_testing/ ./asya_testing/

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e . awscli

CMD ["python3", "asya_runtime.py"]
