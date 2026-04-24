export type PipelineStage = {
  key: string;
  label: string;
  status: "ok" | "idle" | "blocked" | "error";
  primary_value: number;
  secondary_text: string;
};

export type RecentCycleCard = {
  cycle_id: string;
  started_at: string;
  completed_at: string | null;
  duration_seconds: number | null;
  refreshed_symbols_count: number;
  candidates_found: number;
  strategy_analyzed: number;
  strategy_trade_candidates: number;
  strategy_observe_candidates: number;
  strategy_no_trade: number;
  strategy_accepted: number;
  paper_pending_retries: number;
  paper_fills: number;
  pending_entries_before_cycle: number;
  pending_entries_after_cycle: number;
  error_count: number;
  summary: Record<string, any>;
};

export type LiveCycleMonitorBootstrap = {
  ok: boolean;
  account_id: number;
  generated_at: string;
  latest_cycle: {
    cycle_id: string;
    started_at: string;
    completed_at: string | null;
    summary: Record<string, any>;
  } | null;
  summary_strip: {
    cycle_id: string;
    duration_seconds: number | null;
    refreshed_symbols_count: number;
    maintenance_checked: number;
    maintenance_actions_triggered: number;
    candidates_found: number;
    strategy_analyzed: number;
    strategy_trade_candidates: number;
    strategy_observe_candidates: number;
    strategy_no_trade: number;
    strategy_accepted: number;
    risk_approved: number;
    paper_submitted: number;
    paper_pending_retries: number;
    paper_fills: number;
    pending_entries_before_cycle: number;
    pending_entries_after_cycle: number;
    error_count: number;
  } | null;
  pipeline_stages: PipelineStage[];
  recent_cycles: RecentCycleCard[];
  trends: {
    candidates_per_cycle: { label: string; value: number }[];
    trade_candidates_per_cycle?: { label: string; value: number }[];
    observe_per_cycle?: { label: string; value: number }[];
    accepted_per_cycle?: { label: string; value: number }[];
    fills_per_cycle: { label: string; value: number }[];
    errors_per_cycle: { label: string; value: number }[];
  };
  errors: Array<Record<string, unknown>>;
};