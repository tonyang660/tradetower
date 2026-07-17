import type { PerformancePageV2Response } from "../types/performanceV2";
import type { PositionsOrdersV2Response, PositionLifecycleV2Response } from "../types/positionsOrdersV2";
import type { DashboardV2Overview } from "../types/dashboardV2";
import type { DashboardV2LiveResponse } from "../types/dashboardLiveV2";

const BASE_URL = import.meta.env.VITE_DASHBOARD_API_BASE_URL;

if (!BASE_URL) {
  throw new Error("VITE_DASHBOARD_API_BASE_URL is not defined");
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  const text = await res.text();

  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} - ${text.slice(0, 200)}`);
  }

  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(`Expected JSON but received: ${text.slice(0, 120)}`);
  }
}

export function fetchDashboardV2Overview(accountId = 1) {
  return getJson<DashboardV2Overview>(`/dashboard/v2/overview?account_id=${accountId}`);
}

export function fetchDashboardV2Live(accountId = 1, limit = 50) {
  return getJson<DashboardV2LiveResponse>(`/dashboard/v2/live?account_id=${accountId}&limit=${limit}`);
}

export function fetchPositionsOrdersV2(accountId = 1, recentLimit = 20, executedLimit = 50, lifecycleLimit = 10) {
  return getJson<PositionsOrdersV2Response>(
    `/dashboard/v2/positions-orders?account_id=${accountId}&recent_limit=${recentLimit}&executed_limit=${executedLimit}&lifecycle_limit=${lifecycleLimit}`
  );
}

export function fetchPositionLifecycleV2(accountId = 1, positionId: number) {
  return getJson<PositionLifecycleV2Response>(
    `/dashboard/v2/positions-orders/lifecycle?account_id=${accountId}&position_id=${positionId}`
  );
}

export function fetchPerformancePageV2(accountId = 1, limit = 500, equityLimit = 1000) {
  return getJson<PerformancePageV2Response>(
    `/dashboard/v2/performance-page?account_id=${accountId}&limit=${limit}&equity_limit=${equityLimit}`
  );
}
