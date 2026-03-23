FROM python:3.13-slim
WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -q .
