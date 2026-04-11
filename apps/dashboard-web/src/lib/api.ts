import type { BootstrapOverview } from "../types/dashboard";

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

async function postJson<T>(path: string, payload: Record<string, unknown>): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

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

export function fetchBootstrapOverview(accountId = 1) {
  return getJson<BootstrapOverview>(`/bootstrap/overview?account_id=${accountId}`);
}

export function fetchSystemHealth() {
  return getJson(`/system/health`);
}

export function fetchMarketBanner() {
  return getJson(`/market/banner`);
}

export function suspendTrading(accountId = 1) {
  return postJson(`/controls/trading/suspend`, { account_id: accountId });
}

export function resumeTrading(accountId = 1) {
  return postJson(`/controls/trading/resume`, { account_id: accountId });
}

export function enableSchedulerAutoLoop() {
  return postJson(`/controls/scheduler/enable`, {});
}

export function disableSchedulerAutoLoop() {
  return postJson(`/controls/scheduler/disable`, {});
}