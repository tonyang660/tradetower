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