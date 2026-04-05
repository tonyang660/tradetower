FROM python:3.12-slim

WORKDIR /app

COPY services/scheduler/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/scheduler/app /app/app
COPY config /app/config

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

CMD ["python", "/app/app/main.py"]