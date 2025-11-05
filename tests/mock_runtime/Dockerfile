# Mock Runtime for Integration and E2E Tests
# TODO: test on multiple python versions
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONPATH=/app

# Install mock handlers dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy handlers code into ./handlers/ directory
COPY handlers/ handlers/

# Run as non-root user
USER 1000:1000
