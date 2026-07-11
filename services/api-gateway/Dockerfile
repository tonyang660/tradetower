FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app

ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV DEFAULT_MARKET_PROVIDER=blofin
ENV BLOFIN_REST_BASE_URL=https://openapi.blofin.com

CMD ["python", "/app/app/main.py"]