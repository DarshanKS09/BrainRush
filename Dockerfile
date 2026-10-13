# BrainRush backend: Telegram polling + FastAPI in one process.
# Python 3.12 to match the project's requires-python.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps kept minimal (asyncpg builds from wheels; nothing to compile).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml alembic.ini ./
COPY src/ ./src/
COPY alembic/ ./alembic/
RUN pip install --no-cache-dir .

# Migrations are NEVER run automatically: apply them explicitly with
#   alembic upgrade head
# before each rollout (see docs/DEPLOYMENT.md).

# Single process: bot long-polling + API. Run exactly ONE replica/container
# of this image: two competing Telegram pollers would double-answer users.
CMD ["python", "-m", "brainrush", "--serve-api"]
