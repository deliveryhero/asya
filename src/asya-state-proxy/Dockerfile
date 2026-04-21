FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml .
COPY asya_state_proxy/ asya_state_proxy/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir ".[s3,gcs,redis]"
ENTRYPOINT ["sh", "-c", "exec python -m asya_state_proxy.connectors.${ASYA_CONNECTOR}"]
