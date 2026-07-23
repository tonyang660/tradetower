import type {
  BacktestRunConfig,
  BacktestRunDetailResponse,
  BacktestRunListResponse,
  BacktestRunResponse,
  StrategyDetailResponse,
  StrategyListResponse,
} from "../types/backtests";

const BASE_URL = import.meta.env.VITE_DASHBOARD_API_BASE_URL;

if (!BASE_URL) {
  throw new Error("VITE_DASHBOARD_API_BASE_URL is not defined");
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  const text = await res.text();

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} - ${text.slice(0, 240)}`);
  }

  return JSON.parse(text) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} - ${text.slice(0, 240)}`);
  }

  return JSON.parse(text) as T;
}

export function fetchBacktestStrategies() {
  return getJson<StrategyListResponse>("/backtest/strategies");
}

export function fetchBacktestStrategyDetail(strategyName: string) {
  return getJson<StrategyDetailResponse>(
    `/backtest/strategy-detail?strategy_name=${encodeURIComponent(strategyName)}`
  );
}

export function runBacktest(payload: BacktestRunConfig) {
  return postJson<BacktestRunResponse>("/backtest/run", payload);
}

export function fetchBacktestRuns(limit = 10) {
  return getJson<BacktestRunListResponse>(`/backtest/runs?limit=${limit}`);
}

export function fetchBacktestRunDetail(runId: number) {
  return getJson<BacktestRunDetailResponse>(`/backtest/run-detail?run_id=${runId}`);
}
