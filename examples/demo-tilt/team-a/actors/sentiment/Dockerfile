FROM python:3.13-slim
WORKDIR /app

COPY libs/common /deps/common
RUN pip install -q /deps/common

COPY team-a/actors/sentiment /app
RUN pip install -q .

CMD ["python", "-c", "from sentiment_actors.handler import analyze; print(analyze({'text': 'hello world'}))"]
