import { Cpu, Database, GitBranch, ShieldCheck, Tags } from "lucide-react";

function asStringArray(value: unknown, fallback: string[] = []): string[] {
  if (!Array.isArray(value)) return fallback;
  const values = value.map((item) => String(item)).filter(Boolean);
  return values.length ? values : fallback;
}

function textValue(value: unknown, fallback = "—") {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function pickStrategy(detail: any) {
  return detail?.strategy ?? detail?.detail ?? detail?.item ?? detail ?? {};
}

function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "good" | "warn" | "info" }) {
  const cls =
    tone === "good"
      ? "border-emerald-300/20 bg-emerald-500/10 text-emerald-100"
      : tone === "warn"
      ? "border-amber-300/20 bg-amber-500/10 text-amber-100"
      : tone === "info"
      ? "border-cyan-300/20 bg-cyan-500/10 text-cyan-100"
      : "border-white/10 bg-white/8 text-white/60";
  return <span className={`rounded-full border px-2.5 py-1 text-xs ${cls}`}>{children}</span>;
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/18 p-3">
      <div className="text-[10px] uppercase tracking-[0.18em] text-white/35">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-white">{value}</div>
    </div>
  );
}

export default function BacktestStrategyDetailPanel({
  strategyName,
  detail,
  selectedTimeframes,
  dataMode,
  datasetId,
  backendValidation,
}: {
  strategyName: string;
  detail: any;
  selectedTimeframes: string[];
  dataMode: string;
  datasetId: number;
  backendValidation?: any;
}) {
  const strategy = pickStrategy(detail);
  const config = strategy?.config ?? {};
  const version = strategy?.version?.version ?? config?.strategy_version ?? strategy?.metadata?.version ?? strategy?.version ?? "—";
  const family = strategy?.family ?? config?.strategy_family ?? "—";
  const description = strategy?.description ?? config?.description ?? "No description returned.";
  const requiredTimeframes = asStringArray(strategy?.required_timeframes ?? config?.required_timeframes, ["5m", "15m", "4h"]);
  const optionalTimeframes = asStringArray(config?.optional_timeframes, []);
  const requiredIndicators = asStringArray(strategy?.required_indicators ?? config?.required_indicators, []);
  const tags = asStringArray(strategy?.tags ?? config?.tags, ["backtest"]);
  const parityComponents = asStringArray(config?.production_parity_components, []);
  const lifecyclePending = config?.lifecycle_features_not_implemented_yet ?? {};
  const candidateIncluded = Boolean(config?.candidate_filter?.included);
  const backendValid = backendValidation?.validation?.valid ?? backendValidation?.valid ?? null;
  const missingRequired = requiredTimeframes.filter((tf) => !selectedTimeframes.includes(tf));
  const extraSelected = selectedTimeframes.filter((tf) => !requiredTimeframes.includes(tf) && !optionalTimeframes.includes(tf));

  return (
    <section className="rounded-[28px] border border-white/10 bg-white/6 p-5 shadow-glass backdrop-blur-xl">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-lg font-semibold tracking-tight text-white">
            <Cpu size={18} className="text-violet-200" />
            Strategy Detail
          </div>
          <div className="mt-1 text-sm text-white/45">Production-parity context, timeframe requirements, and implementation scope.</div>
        </div>
        {backendValid === true ? <Pill tone="good">Validated</Pill> : backendValid === false ? <Pill tone="warn">Invalid</Pill> : <Pill>Not validated</Pill>}
      </div>

      <div className="space-y-4">
        <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-sm text-white/45">Selected strategy</div>
              <div className="mt-1 text-xl font-semibold text-white">{strategyName}</div>
              <div className="mt-2 max-w-2xl text-sm leading-6 text-white/50">{description}</div>
            </div>
            <div className="flex flex-wrap gap-2">
              {tags.map((tag) => <Pill key={tag}>{tag}</Pill>)}
              {candidateIncluded ? <Pill tone="good">Candidate Filter</Pill> : null}
              {family === "production_parity" ? <Pill tone="info">Production parity</Pill> : null}
            </div>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-4">
          <MiniMetric label="Version" value={textValue(version)} />
          <MiniMetric label="Family" value={textValue(family)} />
          <MiniMetric label="Data mode" value={dataMode} />
          <MiniMetric label="Dataset" value={`#${datasetId}`} />
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-2xl border border-white/10 bg-black/18 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
              <Database size={15} className="text-cyan-200" />
              Timeframe contract
            </div>
            <div className="grid gap-2 text-sm">
              <div className="flex justify-between gap-4"><span className="text-white/45">Required</span><span className="text-white">{requiredTimeframes.join(", ")}</span></div>
              <div className="flex justify-between gap-4"><span className="text-white/45">Optional</span><span className="text-white">{optionalTimeframes.length ? optionalTimeframes.join(", ") : "—"}</span></div>
              <div className="flex justify-between gap-4"><span className="text-white/45">Selected</span><span className="text-white">{selectedTimeframes.join(", ")}</span></div>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {missingRequired.length ? <Pill tone="warn">Missing: {missingRequired.join(", ")}</Pill> : <Pill tone="good">Required TFs selected</Pill>}
              {extraSelected.length ? <Pill>Extra: {extraSelected.join(", ")}</Pill> : null}
            </div>
          </div>

          <div className="rounded-2xl border border-white/10 bg-black/18 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
              <GitBranch size={15} className="text-emerald-200" />
              Production parity pipeline
            </div>
            <div className="flex flex-wrap gap-2">
              {(parityComponents.length ? parityComponents : ["feature_factory_v2", "candidate_filter_v2", "strategy_signal_v2"]).map((item) => (
                <Pill key={item} tone="info">{item}</Pill>
              ))}
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-black/18 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
            <Tags size={15} className="text-violet-200" />
            Required indicators / features
          </div>
          <div className="flex flex-wrap gap-2">
            {(requiredIndicators.length ? requiredIndicators : ["market_snapshot_v2", "candidate_filter_v2", "strategy_signal_v2"]).map((item) => (
              <Pill key={item}>{item}</Pill>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-amber-300/15 bg-amber-500/8 p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-amber-100">
            <ShieldCheck size={15} />
            Honest scope boundary
          </div>
          <div className="text-sm leading-6 text-amber-100/70">
            Phase 17 displays configuration and results. Phase 18 owns realistic order/position lifecycle simulation.
          </div>
          {Object.keys(lifecyclePending).length ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {Object.keys(lifecyclePending).map((key) => <Pill key={key} tone="warn">{key}</Pill>)}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
