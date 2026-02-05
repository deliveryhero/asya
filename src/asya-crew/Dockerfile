# TODO: good to test multiple Python versions 3.7+
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONPATH=/app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -q -r requirements.txt

# Copy handlers code into ./handlers/ directory
COPY handlers/ handlers/
