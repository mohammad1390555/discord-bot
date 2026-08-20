FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
COPY migrations ./migrations
COPY .env.example ./

RUN useradd --create-home --uid 10001 bot \
    && mkdir -p /app/data \
    && chown -R bot:bot /app
USER bot

CMD ["python", "-m", "bot"]
