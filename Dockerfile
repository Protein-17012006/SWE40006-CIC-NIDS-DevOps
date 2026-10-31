# One image for every environment: the dashboard by default,
# `python -m pipeline <command>` for the one-off ECS tasks.
FROM python:3.12.16-slim-trixie

# No file watching in containers: code never changes there, and polling costs CPU
ENV PYTHONPATH=/srv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

WORKDIR /srv

# Dependencies first, so code changes reuse this layer
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY .streamlit/ .streamlit/
COPY alembic.ini .
COPY migrations/ migrations/
COPY app/ app/
COPY pipeline/ pipeline/
COPY contracts/ contracts/

RUN useradd --create-home --uid 10001 cicnids
USER cicnids

EXPOSE 8501
CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
