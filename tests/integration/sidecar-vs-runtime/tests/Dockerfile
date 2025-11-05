# test runner
FROM python:3.13-slim
WORKDIR /app

# Copy requirements and install dependencies
COPY . .
RUN pip install -q --no-cache-dir -r requirements.txt

USER 1000:1000
