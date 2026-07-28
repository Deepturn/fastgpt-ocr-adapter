# Linux/amd64 manifest for vllm/vllm-openai:v0.21.0-cu129.
ARG MINERU_PLATFORM=linux/amd64
FROM --platform=${MINERU_PLATFORM} docker.io/vllm/vllm-openai:v0.21.0-cu129@sha256:31577e8a2dc0688ce695c98fcf0d3c4a735d74cdcfaf8a79e65e55b2232445e7

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/models/home \
    MINERU_MODEL_SOURCE=local \
    MINERU_TOOLS_CONFIG_JSON=/models/mineru.json \
    MINERU_API_OUTPUT_ROOT=/work/output \
    MINERU_API_ENABLE_FASTAPI_DOCS=0 \
    MINERU_API_MAX_CONCURRENT_REQUESTS=1 \
    MINERU_API_TASK_RETENTION_SECONDS=900 \
    MINERU_PROCESSING_WINDOW_SIZE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fontconfig fonts-noto-cjk fonts-noto-core \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install --no-cache-dir "mineru[pipeline]==3.4.4" \
    && python3 -m pip cache purge

WORKDIR /work
RUN mkdir -p /models/home /work/output

COPY deploy/mineru/entrypoint.sh /usr/local/bin/mineru-entrypoint
ENTRYPOINT ["/bin/bash", "/usr/local/bin/mineru-entrypoint"]

EXPOSE 8000
CMD ["mineru-api", "--host", "0.0.0.0", "--port", "8000"]
