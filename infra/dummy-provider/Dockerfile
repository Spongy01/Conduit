FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn

COPY tests/dummy_providers ./tests/dummy_providers

ENV DUMMY_APP=tests.dummy_providers.openai_dummy:app
ENV DUMMY_PORT=8001

CMD ["sh", "-c", "uvicorn ${DUMMY_APP} --host 0.0.0.0 --port ${DUMMY_PORT}"]
