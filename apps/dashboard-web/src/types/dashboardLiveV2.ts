export type DashboardV2ServiceBlock<T = unknown> = {
  ok: boolean;
  data: T | null;
  error: unknown | null;
};

export type DashboardV2LiveError = {
  source?: string;
  path?: string;
  status_code?: number | null;
  error?: unknown;
};

export type DashboardV2Cycle = {
  cycle_id?: string;
  started_at?: string;
  completed_at?: string | null;
  status?: string;
  summary?: Record<string, any>;
};

export type DashboardV2LiveResponse = {
  ok: boolean;
  partial: boolean;
  dashboard_aggregation_v2_version: string;
  account_id: number;
  generated_at: string;
  latest_cycle: Record<string, any> | null;
  cycles: DashboardV2Cycle[];
  open_positions: Array<Record<string, any>>;
  open_orders: Array<Record<string, any>>;
  services: {
    latest_cycle?: DashboardV2ServiceBlock;
    cycle_history?: DashboardV2ServiceBlock;
    open_positions?: DashboardV2ServiceBlock;
    open_orders?: DashboardV2ServiceBlock;
    [key: string]: DashboardV2ServiceBlock | undefined;
  };
  errors: DashboardV2LiveError[];
};
