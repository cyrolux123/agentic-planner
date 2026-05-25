# ──────────────────────────────────────────────────────────────────────────────
# Resource-Constrained Agentic Planning Loop
# Runs against an Ollama instance on the host machine.
# Primary model: llama3   Fallback: mistral
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# System deps for duckduckgo-search (needs curl/ssl)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Ollama host — override at runtime via -e or docker-compose environment
ENV OLLAMA_HOST=http://host.docker.internal:11434
# Primary model: llama3. Falls back to mistral automatically if not found.
ENV OLLAMA_MODEL=llama3

# Default: show help. Override CMD in docker-compose or with `docker run`.
CMD ["python", "main.py", "--help"]