# test runner
FROM python:3.13-slim
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt ./requirements.txt
RUN pip install -q --no-cache-dir -r requirements.txt

COPY *.py ./tests/

USER 1000:1000
