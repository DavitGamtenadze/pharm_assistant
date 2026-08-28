FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY prompts ./prompts

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "pharm_assistant.main:app", "--host", "0.0.0.0", "--port", "8000"]
