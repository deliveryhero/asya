FROM python:3.13-slim
WORKDIR /app

COPY pyproject.toml .
COPY asya_state_proxy/ asya_state_proxy/

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install ".[s3,gcs,redis]"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && mkdir -p /var/run/asya/state \
    && chmod 777 /var/run/asya/state
USER nobody

ENTRYPOINT ["/entrypoint.sh"]
