# --- CEMA cUAS Backend image ---
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (bcrypt/cryptography build)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
# Strip Emergent-internal packages that are not resolvable outside the
# Emergent PyPI index. This app does not import them.
RUN sed -i -E '/^(emergentintegrations)([<>=~!].*)?$/d' requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

EXPOSE 8001

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
