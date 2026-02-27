FROM python:3.13-slim
WORKDIR /app
ENV PYTHONPATH=/app

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -q -r requirements.txt

COPY asya_lab/ asya_lab/
