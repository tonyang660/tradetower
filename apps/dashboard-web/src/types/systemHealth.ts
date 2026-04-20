export type HealthStatus = "healthy" | "degraded" | "offline" | "unknown";
export type OverallStatus = "operational" | "degraded" | "partial_outage" | "offline";

export type SystemHealthOverall = {
  status: OverallStatus;
  message: string;
  healthy_services: number;
  total_services: number;
  average_latency_ms: number | null;
  incidents_open: number;
  last_successful_cycle_at: string | null;
};

export type SystemHealthSummaryStrip = {
  overall_status: OverallStatus;
  healthy_services: number;
  average_latency_ms: number | null;
  scheduler_state: "enabled" | "disabled";
  last_cycle_age_seconds: number | null;
  issues_open: number;
};

export type SystemHealthService = {
  service_key: string;
  service_name: string;
  ok: boolean;
  reachable: boolean;
  status: HealthStatus;
  status_code: number | null;
  latency_ms: number | null;
  last_checked_at: string | null;
  last_ok_at: string | null;
  message: string | null;
  payload?: Record<string, unknown>;
};

export type DependencyFlowNode = {
  service_key: string;
  service_name: string;
  status: HealthStatus;
};

export type AvailabilityTimelinePoint = {
  label: string;
  status: HealthStatus;
};

export type AvailabilityTimelineRow = {
  service_key: string;
  service_name: string;
  points: AvailabilityTimelinePoint[];
};

export type SystemHealthFreshness = {
  overview_generated_at: string | null;
  performance_generated_at: string | null;
  last_scheduler_cycle_at: string | null;
  last_cycle_age_seconds: number | null;
  scheduler_auto_loop_enabled: boolean | null;
  scheduler_loop_interval_seconds: number | null;
};

export type SystemHealthIssue = {
  level: "info" | "warning" | "critical";
  code: string;
  title: string;
  detail: string;
  detected_at: string;
};

export type SystemHealthBootstrapResponse = {
  ok: boolean;
  account_id: number;
  generated_at: string;
  overall: SystemHealthOverall;
  summary_strip: SystemHealthSummaryStrip;
  services: SystemHealthService[];
  dependency_flow: DependencyFlowNode[];
  availability_timeline: AvailabilityTimelineRow[];
  freshness: SystemHealthFreshness;
  issues: SystemHealthIssue[];
  errors: Array<Record<string, unknown>>;
};