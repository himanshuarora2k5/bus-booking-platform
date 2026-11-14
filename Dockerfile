# syntax=docker/dockerfile:1

# ---- base: Python + the exact pinned libraries (shared by test and runtime) ----
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- test: adds test tools + tests. Never shipped. ----
FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY pyproject.toml ./
COPY app ./app
COPY db ./db
COPY tests ./tests
CMD ["pytest", "-q", "-p", "no:logging"]

# ---- runtime: the image we actually run (last stage = default build target) ----
FROM base AS runtime
ARG APP_VERSION=dev
# Chaos switch (off by default). The rollback drill builds one deliberately broken release with it on.
ARG FAULT_READY_FAIL=false
ENV APP_VERSION=${APP_VERSION} \
    FAULT_READY_FAIL=${FAULT_READY_FAIL}
# Run as an ordinary user with no login shell and no home directory, not as root.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
COPY app ./app
COPY db ./db
USER 10001
EXPOSE 8000
# Docker marks the container "unhealthy" if /health/ready stops answering 200.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=4)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
