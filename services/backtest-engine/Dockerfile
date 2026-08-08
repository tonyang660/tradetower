FROM python:3.12-slim
WORKDIR /app
COPY services/backtest-engine/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY services/backtest-engine/app /app/app
# Read-only production references copied into the backtest image. The adapters
# under /app/app import these exact policy modules; production services and
# their runtime containers are not changed.
COPY services/feature-factory/app /app/production/feature_factory
COPY services/candidate-filter/app /app/production/candidate_filter
COPY services/strategy-engine/app /app/production/strategy_engine
COPY services/risk-engine/app /app/production/risk_engine
COPY services/trade-guardian/app/near_tp_reversal_policy.py /app/production/trade_guardian/near_tp_reversal_policy.py
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
CMD ["python", "/app/app/main.py"]
