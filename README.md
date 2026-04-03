# trading-platform

Development platform for trading infrastructure and future internal applications.

## Environments
- local dev: laptop
- staging: staging1 (10.0.0.40)
- core infra: homelab shared services
- inference providers: local CPU, gpu-node1

## Main components
- data-hub
- feature-factory
- candidate-filter
- brain-orchestrator
- trade-guardian
- risk-engine
- paper-execution
- evaluator
- api-gateway

## Principles
- deterministic replay
- hard non-AI risk enforcement
- prompt/schema versioning
- secrets outside git
