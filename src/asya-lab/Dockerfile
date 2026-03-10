FROM python:3.13-slim
WORKDIR /app
ENV PYTHONPATH=/app

COPY pyproject.toml .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -q .

COPY asya_lab/ asya_lab/
