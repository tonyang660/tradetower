import type {
  BacktestRunConfig,
  BacktestRunDetailResponse,
  BacktestRunListResponse,
  BacktestRunResponse,
  BacktestJobProgress,
  BacktestAnalyticsResponse,
  BacktestChartDataResponse,
  BacktestPagedRowsResponse,
  BacktestResultBundleResponse,
  BacktestValidationResponse,
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

function isNotFound(error: unknown) {
  return error instanceof Error && error.message.startsWith("Request failed: 404");
}

function pageFromBundle(
  payload: BacktestResultBundleResponse,
  key: "positions" | "exit_legs" | "position_events",
  limit: number,
  offset: number,
): BacktestPagedRowsResponse {
  const section = (payload as any)?.[key];
  const sectionPresent = section !== null && section !== undefined;
  const allRows = Array.isArray(section)
    ? section
    : Array.isArray(section?.rows)
      ? section.rows
      : [];
  const rows = allRows.slice(offset, offset + limit);
  const total = typeof section?.total === "number" ? section.total : allRows.length;

  return {
    ok: payload.ok,
    run_id: payload.run_id,
    [key]: rows,
    rows,
    total,
    count: rows.length,
    limit,
    offset,
    has_more: offset + rows.length < total,
    available: typeof section?.available === "boolean" ? section.available : sectionPresent,
    reason: typeof section?.reason === "string" ? section.reason : sectionPresent ? null : `${key}_unavailable`,
  };
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


export function validateBacktestRunConfig(payload: BacktestRunConfig) {
  return postJson<BacktestValidationResponse>("/backtest/validate-run", payload);
}


export function startBacktestAsync(payload: BacktestRunConfig) {
  return postJson<BacktestJobProgress>("/backtest/start", payload);
}

export function fetchBacktestProgress(jobId: string) {
  return getJson<BacktestJobProgress>(`/backtest/progress?job_id=${encodeURIComponent(jobId)}`);
}

export function cancelBacktest(jobId: string) {
  return postJson<BacktestJobProgress>("/backtest/cancel", { job_id: jobId });
}


export function fetchBacktestAnalytics(runId: number) {
  return getJson<BacktestAnalyticsResponse>(`/backtest/analytics?run_id=${runId}`);
}


export function fetchBacktestCharts(runId: number) {
  return getJson<BacktestChartDataResponse>(`/backtest/charts?run_id=${runId}`);
}


export function fetchBacktestTrades(runId: number, limit = 250, offset = 0) {
  return getJson<BacktestPagedRowsResponse>(`/backtest/trades?run_id=${runId}&limit=${limit}&offset=${offset}`);
}

export async function fetchBacktestExitLegs(runId: number, limit = 250, offset = 0) {
  try {
    return await getJson<BacktestPagedRowsResponse>(`/backtest/exit-legs?run_id=${runId}&limit=${limit}&offset=${offset}`);
  } catch (error) {
    if (!isNotFound(error)) throw error;
    const legacy = await fetchBacktestTrades(runId, limit, offset);
    return { ...legacy, exit_legs: legacy.trades ?? legacy.rows ?? [] };
  }
}

export async function fetchBacktestPositions(runId: number, limit = 250, offset = 0) {
  try {
    return await getJson<BacktestPagedRowsResponse>(`/backtest/positions?run_id=${runId}&limit=${limit}&offset=${offset}`);
  } catch (error) {
    if (!isNotFound(error)) throw error;
    return pageFromBundle(await fetchBacktestResultBundle(runId), "positions", limit, offset);
  }
}

export async function fetchBacktestPositionEvents(runId: number, limit = 1000, offset = 0) {
  try {
    return await getJson<BacktestPagedRowsResponse>(`/backtest/position-events?run_id=${runId}&limit=${limit}&offset=${offset}`);
  } catch (error) {
    if (!isNotFound(error)) throw error;
    return pageFromBundle(await fetchBacktestResultBundle(runId), "position_events", limit, offset);
  }
}

export function fetchBacktestLogs(runId: number, limit = 250, offset = 0) {
  return getJson<BacktestPagedRowsResponse>(`/backtest/logs?run_id=${runId}&limit=${limit}&offset=${offset}`);
}

export function fetchBacktestResultBundle(runId: number) {
  return getJson<BacktestResultBundleResponse>(`/backtest/result-bundle?run_id=${runId}`);
}
