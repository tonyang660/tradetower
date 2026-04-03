FROM python:3.12-slim

WORKDIR /app
COPY app /app/app

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

CMD ["python", "/app/app/main.py"]