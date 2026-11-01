# The upstream image contains the compiled ARM64 CPU backend, not CUDA vLLM.
FROM vllm/vllm-openai-cpu:v0.27.0-arm64@sha256:d8ad98d4aa9ae41674b825d505184d55c2ef1f4a9c77e732e53c5caf9a9e5d51
ENV HOME=/tmp \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/tmp/huggingface \
    XDG_CACHE_HOME=/tmp/cache \
    TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor \
    TRITON_CACHE_DIR=/tmp/triton \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    VLLM_NO_USAGE_STATS=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
COPY scripts/check_lock.py /app/check_lock.py
# All dependencies are already in the digest-pinned base image. Do not resolve
# or upgrade anything during this build. Check the full list, including transitives.
RUN python /app/check_lock.py /app/requirements.txt && python -m pip check
COPY app /app/app
COPY config /app/config
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["python", "-m", "app.serve"]
