FROM python:3.13-slim AS app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /srv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PATH="/srv/.venv/bin:$PATH" MODELS_DIR=/models HF_HUB_OFFLINE=0
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
# Speech models are part of the image, so a call never waits for a download: the agent's voice, a second voice
# (the evaluation's customers), and Whisper base.en for the CPU.
RUN mkdir -p /models/piper /models/whisper \
    && python -m piper.download_voices --data-dir /models/piper en_US-lessac-medium en_US-ryan-medium \
    && python -c "from faster_whisper import download_model; download_model('base.en', output_dir='/models/whisper/base.en')"
COPY . .
RUN useradd --system --uid 10001 app && chown -R app /srv /models
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

# The GPU image: CUDA libraries for faster-whisper (CTranslate2) and the larger model. docker-compose.gpu.yml.
FROM app AS gpu
USER root
RUN uv pip install --python /srv/.venv/bin/python nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*" \
    && python -c "from faster_whisper import download_model; download_model('small.en', output_dir='/models/whisper/small.en')" \
    && chown -R app /models
ENV LD_LIBRARY_PATH=/srv/.venv/lib/python3.13/site-packages/nvidia/cublas/lib:/srv/.venv/lib/python3.13/site-packages/nvidia/cudnn/lib
USER app

# Test image: the same models plus the development tools; tests are mounted, not copied.
FROM app AS test
USER root
RUN uv sync --frozen && chown -R app /srv
USER app
