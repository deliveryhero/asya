FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml .
COPY asya_state_proxy/ asya_state_proxy/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install ".[s3,gcs,redis]"
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
