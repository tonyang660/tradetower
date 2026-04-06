FROM python:3.12-slim

WORKDIR /app

COPY services/strategy-engine/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/strategy-engine/app /app/app

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

CMD ["python", "/app/app/main.py"]