FROM node:24-bookworm-slim AS frontend
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/src ZELVO_HOST=0.0.0.0 PORT=8000
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libgl1 libglu1-mesa libxrender1 libatomic1 libstdc++6 libexpat1 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir . eclipse-sumo==1.26.0
RUN python -c "import libsumo; from zelvo.runtime import discover_tools; print(discover_tools().versions)"
COPY models/ ./models/
COPY scenarios/ ./scenarios/
COPY --from=frontend /web/dist/ ./frontend/dist/
RUN useradd --create-home zelvo && mkdir -p results/live && chown -R zelvo:zelvo results
USER zelvo
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT','8000') + '/api/health', timeout=4)"
CMD ["python", "-m", "zelvo.api"]
