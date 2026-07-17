import type { PerformanceBootstrapResponse } from "./performance";

export type PerformancePageV2Error = {
  source?: string;
  path?: string;
  status_code?: number | null;
  error?: unknown;
};

export type PerformancePageV2Response = PerformanceBootstrapResponse & {
  partial?: boolean;
  performance_page_v2_version?: string;
  v2?: {
    performance?: Record<string, any> | null;
    pnl_convention?: Record<string, any> | null;
    cost_breakdown?: Record<string, any> | null;
    leg_summary?: Record<string, any> | null;
    latest_equity?: Record<string, any> | null;
  };
  services?: Record<string, {
    ok: boolean;
    data: unknown | null;
    error: PerformancePageV2Error | null;
  }>;
  errors: PerformancePageV2Error[];
};
