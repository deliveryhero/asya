FROM python:3.13-slim
WORKDIR /app

COPY . /app
RUN pip install -q .

CMD ["python", "-c", "from summarizer.handler import summarize; print(summarize({'text': 'hello world this is a test'}))"]
