import type { BootstrapOverview } from "../types/dashboard";

const BASE_URL = import.meta.env.VITE_DASHBOARD_API_BASE_URL;

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }
  return res.json();
}

export function fetchBootstrapOverview(accountId = 1) {
  return getJson<BootstrapOverview>(`/bootstrap/overview?account_id=${accountId}`);
}

export function fetchSystemHealth() {
  return getJson(`/system/health`);
}

export function fetchMarketBanner() {
  return getJson(`/market/banner`);
}
