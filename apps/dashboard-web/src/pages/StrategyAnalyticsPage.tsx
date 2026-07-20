import { useEffect, useMemo, useState } from "react";
import { fetchStrategyAnalyticsPageV2 } from "../lib/dashboardV2";
import { useSelectedAccount } from "../lib/accountContext";
import {
  buildStrategyAnalyticsViewModel,
  type StrategyAnalyticsViewModel,
} from "../lib/strategyAnalytics";
import type { StrategyAnalyticsPageV2Response } from "../types/strategyAnalyticsV2";

import StrategyAnalyticsSummaryStrip from "../components/strategy-analytics/StrategyAnalyticsSummaryStrip";
import ScoreBucketTable from "../components/strategy-analytics/ScoreBucketTable";
import SymbolEdgeTable from "../components/strategy-analytics/SymbolEdgeTable";
import HoldingTimePanel from "../components/strategy-analytics/HoldingTimePanel";
import ExitOutcomePanel from "../components/strategy-analytics/ExitOutcomePanel";
import FeePressurePanel from "../components/strategy-analytics/FeePressurePanel";

export default function StrategyAnalyticsPage() {
  const { selectedAccountId, selectedAccount } = useSelectedAccount();

  const [payload, setPayload] = useState<StrategyAnalyticsPageV2Response | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load(showLoading = false, showRefreshing = false) {
    try {
      if (showLoading) setLoading(true);
      if (showRefreshing) setRefreshing(true);
      setError(null);

      const result = await fetchStrategyAnalyticsPageV2(selectedAccountId, 500, 100);
      setPayload(result);
      setLastUpdated(new Date());
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load strategy analytics.";
      setError(message);
    } finally {
      if (showLoading) setLoading(false);
      if (showRefreshing) setRefreshing(false);
    }
  }

  useEffect(() => {
    void load(true, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAccountId]);

  const model: StrategyAnalyticsViewModel | null = useMemo(() => {
    if (!payload) return null;
    return buildStrategyAnalyticsViewModel(payload);
  }, [payload]);

  const header = (
    <div>
      <h1 className="text-2xl font-semibold text-white">Strategy Analytics</h1>
      <p className="mt-1 text-sm text-white/55">
        Edge attribution, selection quality, and trade behavior diagnostics.
      </p>
      <div className="mt-2 text-xs text-white/40">
        Account #{selectedAccountId}
        {selectedAccount?.account_name ? ` · ${selectedAccount.account_name}` : ""}
      </div>
    </div>
  );

  if (loading) {
    return (
      <div className="space-y-6">
        {header}
        <div className="rounded-2xl border border-white/10 bg-white/5 p-6 text-white/70">
          Loading strategy analytics for account #{selectedAccountId}...
        </div>
      </div>
    );
  }

  if (error || !model) {
    return (
      <div className="space-y-6">
        {header}
        <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 p-6 text-rose-200">
          Failed to load strategy analytics for account #{selectedAccountId}. {error ?? "Unknown error."}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        {header}

        <div className="flex items-center gap-3">
          <div className="rounded-full border border-cyan-300/15 bg-cyan-500/10 px-3 py-1 text-xs text-cyan-100/75">
            Account-filtered
          </div>

          {lastUpdated ? (
            <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/55">
              Updated {lastUpdated.toLocaleString()}
            </div>
          ) : model.generatedAt ? (
            <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/55">
              Generated {new Date(model.generatedAt).toLocaleString()}
            </div>
          ) : null}

          <button
            type="button"
            onClick={() => void load(false, true)}
            disabled={refreshing}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white transition hover:bg-white/10 disabled:opacity-50"
          >
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </header>

      {payload?.account_id && payload.account_id !== selectedAccountId ? (
        <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-100">
          Account mismatch: UI requested account #{selectedAccountId}, but API returned account #{payload.account_id}.
        </div>
      ) : null}

      {payload?.partial ? (
        <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-100">
          Strategy Analytics V2 loaded with partial data. Core V2 decision analytics are shown; older trade-outcome sections may be unavailable until their V2 equivalents are added.
        </div>
      ) : null}

      <StrategyAnalyticsSummaryStrip summary={model.summary} />

      <ScoreBucketTable items={model.scoreBuckets} />

      <SymbolEdgeTable items={model.symbols} />

      <div className="grid gap-6 xl:grid-cols-2">
        <HoldingTimePanel section={model.holdingTimes} />
        <ExitOutcomePanel section={model.exitOutcomes} />
      </div>

      <FeePressurePanel section={model.feePressure} />
    </div>
  );
}
