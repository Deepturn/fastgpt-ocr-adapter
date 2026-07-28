FROM python:3.11.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 adapter \
    && useradd --uid 10001 --gid adapter --no-create-home --shell /usr/sbin/nologin adapter

COPY requirements.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir \
      pip==26.1.2 \
      wheel==0.46.2 \
    && python -m pip install --no-cache-dir -r /tmp/requirements.lock \
    && python -m pip uninstall -y setuptools wheel

COPY src /app/src

USER 10001:10001
EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=4 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health/ready', timeout=3)"]

CMD ["uvicorn", "fastgpt_ocr_adapter.app:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1", "--no-server-header"]
