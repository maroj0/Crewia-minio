FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml README.md ./
COPY agents ./agents
COPY knowledge ./knowledge
COPY tools ./tools
COPY callbacks ./callbacks
COPY crews ./crews
COPY crew.jsonc ./crew.jsonc
COPY service ./service

RUN pip install --upgrade pip && pip install .

EXPOSE 8000

CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000"]
