import type { StrategyAnalyticsBootstrapResponse } from "./strategyAnalytics";

export type StrategyAnalyticsPageV2Error = {
  source?: string;
  path?: string;
  status_code?: number | null;
  error?: unknown;
};

export type StrategyAnalyticsPageV2Response = StrategyAnalyticsBootstrapResponse & {
  partial?: boolean;
  strategy_analytics_page_v2_version?: string;
  v2?: {
    strategy_analytics?: Record<string, any> | null;
    summary?: Record<string, any> | null;
    regimes?: Array<Record<string, any>>;
    setups?: Array<Record<string, any>>;
    score_components?: Record<string, any> | null;
    risk_rejections?: Record<string, any> | null;
  };
  services?: Record<string, {
    ok: boolean;
    data: unknown | null;
    error: StrategyAnalyticsPageV2Error | null;
  }>;
  errors: StrategyAnalyticsPageV2Error[];
};
