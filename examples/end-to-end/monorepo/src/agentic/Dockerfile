FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app/
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
