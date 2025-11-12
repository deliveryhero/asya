FROM python:3.13-slim

WORKDIR /opt/asya

COPY pyproject.toml requirements.txt ./
COPY asya_testing/ ./asya_testing/

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e .

CMD ["python3", "asya_runtime.py"]
