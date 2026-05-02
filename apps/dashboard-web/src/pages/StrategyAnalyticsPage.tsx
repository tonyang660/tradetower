import { useEffect, useMemo, useState } from "react";
import { fetchStrategyAnalyticsBootstrap } from "../lib/api";
import {
  buildStrategyAnalyticsViewModel,
  type StrategyAnalyticsViewModel,
} from "../lib/strategyAnalytics";
import type { StrategyAnalyticsBootstrapResponse } from "../types/strategyAnalytics";

import StrategyAnalyticsSummaryStrip from "../components/strategy-analytics/StrategyAnalyticsSummaryStrip";
import ScoreBucketTable from "../components/strategy-analytics/ScoreBucketTable";
import SymbolEdgeTable from "../components/strategy-analytics/SymbolEdgeTable";
import HoldingTimePanel from "../components/strategy-analytics/HoldingTimePanel";
import ExitOutcomePanel from "../components/strategy-analytics/ExitOutcomePanel";
import FeePressurePanel from "../components/strategy-analytics/FeePressurePanel";

export default function StrategyAnalyticsPage() {
  const [payload, setPayload] = useState<StrategyAnalyticsBootstrapResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setLoading(true);
      setError(null);
      const result = await fetchStrategyAnalyticsBootstrap(1);
      setPayload(result);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load strategy analytics.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const model: StrategyAnalyticsViewModel | null = useMemo(() => {
    if (!payload) return null;
    return buildStrategyAnalyticsViewModel(payload);
  }, [payload]);

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-white">Strategy Analytics</h1>
          <p className="mt-1 text-sm text-white/55">
            Edge attribution, selection quality, and trade behavior diagnostics.
          </p>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/5 p-6 text-white/70">
          Loading strategy analytics...
        </div>
      </div>
    );
  }

  if (error || !model) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold text-white">Strategy Analytics</h1>
          <p className="mt-1 text-sm text-white/55">
            Edge attribution, selection quality, and trade behavior diagnostics.
          </p>
        </div>
        <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 p-6 text-rose-200">
          Failed to load strategy analytics. {error ?? "Unknown error."}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-white">Strategy Analytics</h1>
          <p className="mt-1 text-sm text-white/55">
            Edge attribution, selection quality, and trade behavior diagnostics.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {model.generatedAt ? (
            <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/55">
              Updated {new Date(model.generatedAt).toLocaleString()}
            </div>
          ) : null}

          <button
            type="button"
            onClick={() => void load()}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white transition hover:bg-white/10"
          >
            Refresh
          </button>
        </div>
      </header>

      {model.hasErrors ? (
        <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-100">
          Some analytics sections may be incomplete. Partial data is being shown.
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