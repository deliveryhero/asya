# TODO: good to test multiple Python versions 3.7+
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONPATH=/app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -q -r requirements.txt

# Copy crew code into ./asya_crew/ directory
COPY asya_crew/ asya_crew/
