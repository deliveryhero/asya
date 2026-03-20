FROM python:3.13-slim
WORKDIR /app

COPY . /app
RUN pip install -q .

CMD ["python", "-c", "from translator.handler import translate; print(translate({'text': 'hello world'}))"]
