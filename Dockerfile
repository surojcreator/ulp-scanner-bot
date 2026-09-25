FROM python:3.10-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure directory permissions for non-root users (Hugging Face Spaces UID 1000)
RUN mkdir -p data/incoming data/output data/temp && \
    useradd -m -u 1000 user && \
    chown -R user:user /app

USER user

EXPOSE 7860

CMD ["python", "run.py"]
