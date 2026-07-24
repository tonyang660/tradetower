import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  BarChart3,
  CalendarDays,
  Database,
  Loader2,
  Play,
  RefreshCcw,
  ShieldCheck,
  SlidersHorizontal,
  Zap,
} from "lucide-react";
import {
  fetchBacktestRuns,
  fetchBacktestStrategies,
  fetchBacktestStrategyDetail,
  runBacktest,
  validateBacktestRunConfig,
} from "../lib/backtestApi";
import type { BacktestRunConfig, BacktestRunResponse, BacktestValidationResponse } from "../types/backtests";
import BacktestStrategyDetailPanel from "../components/backtest/BacktestStrategyDetailPanel";
import BacktestValidationPanel from "../components/backtest/BacktestValidationPanel";

const DEFAULT_CONFIG: BacktestRunConfig = {
  strategy_name: "tradetower_baseline_v1",
  strategy_version: "0.2.0",
  symbols: ["BTCUSDT", "ETHUSDT"],
  timeframes: ["5m", "15m", "1h", "4h"],
  cycle_timeframe: "15m",
  start_time: "2024-01-01T00:00:00Z",
  end_time: "2024-03-01T00:00:00Z",
  starting_capital: 2000,
  max_cycles: 1000,
  risk_per_trade_pct: 1,
  maker_fee_bps: 2,
  taker_fee_bps: 6,
  limit_order_fill_ratio: 0.8,
  slippage_bps: 3,
  spread_bps: 0,
  execution_mode: "phase17_simple_fill_current_engine",
  macro_bias_mode: "strategy_default",
  regime_model_version: "phase16f_feature_factory_v2",
  guardian_max_position_leverage: 15,
  guardian_account_max_notional_multiplier: 10,
  guardian_max_account_exposure_pct: 100,
  data_mode: "local_historical_dataset",
  dataset_id: 1,
  warmup_required_bars: 250,
  preflight_strict: true,
  strategy_validation_strict_timeframes: false,
};

const TIMEFRAME_OPTIONS = ["5m", "15m", "1h", "4h", "1d"];

function asArray(value: unknown): any[] {
  return Array.isArray(value) ? value : [];
}

function asStringArray(value: unknown, fallback: string[] = []): string[] {
  if (!Array.isArray(value)) return fallback;
  const values = value
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "name" in item) return String((item as any).name);
      if (item && typeof item === "object" && "strategy_name" in item) return String((item as any).strategy_name);
      return "";
    })
    .filter(Boolean);
  return values.length ? values : fallback;
}

function getStrategyObject(payload: any): any {
  if (!payload) return null;
  return payload.strategy ?? payload.detail ?? payload.item ?? payload;
}

function normalizeStrategies(payload: any): string[] {
  const merged = [
    ...asStringArray(payload?.items),
    ...asStringArray(payload?.strategies),
    ...asStringArray(payload?.data),
  ];
  return Array.from(new Set(merged.length ? merged : ["tradetower_baseline_v1"]));
}

function normalizeRuns(payload: any): any[] {
  return asArray(payload?.runs ?? payload?.items ?? payload?.data);
}

function textValue(value: unknown, fallback = "—") {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function money(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(2)}%`;
}

function numberFmt(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

function Panel({ title, subtitle, icon, children }: { title: string; subtitle?: string; icon?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-[28px] border border-white/10 bg-white/6 p-5 shadow-glass backdrop-blur-xl">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-lg font-semibold tracking-tight text-white">
            {icon}
            {title}
          </div>
          {subtitle ? <div className="mt-1 text-sm text-white/45">{subtitle}</div> : null}
        </div>
      </div>
      {children}
    </section>
  );
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <div className="mb-1.5 text-xs font-medium uppercase tracking-[0.16em] text-white/40">{label}</div>
      {children}
      {hint ? <div className="mt-1 text-xs text-white/35">{hint}</div> : null}
    </label>
  );
}

function inputClass() {
  return "w-full rounded-2xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-white outline-none transition placeholder:text-white/25 focus:border-cyan-300/40 focus:bg-black/30";
}

function MetricTile({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "good" | "bad" }) {
  const color = tone === "good" ? "text-emerald-200" : tone === "bad" ? "text-rose-200" : "text-white";
  return (
    <div className="rounded-2xl border border-white/10 bg-black/18 p-4">
      <div className="text-xs uppercase tracking-[0.18em] text-white/35">{label}</div>
      <div className={`mt-2 truncate text-2xl font-semibold ${color}`}>{value}</div>
    </div>
  );
}

export default function BacktestPage() {
  const [config, setConfig] = useState<BacktestRunConfig>(DEFAULT_CONFIG);
  const [symbolsText, setSymbolsText] = useState(DEFAULT_CONFIG.symbols.join(", "));
  const [strategies, setStrategies] = useState<string[]>(["tradetower_baseline_v1"]);
  const [strategyDetail, setStrategyDetail] = useState<any | null>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestRunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastStartedAt, setLastStartedAt] = useState<Date | null>(null);
  const [backendValidation, setBackendValidation] = useState<BacktestValidationResponse | null>(null);
  const [validatingConfig, setValidatingConfig] = useState(false);

  useEffect(() => {
    loadBootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadStrategyDetail(config.strategy_name);
  }, [config.strategy_name]);

  async function loadBootstrap() {
    try {
      const [strategyPayload, runPayload] = await Promise.all([
        fetchBacktestStrategies(),
        fetchBacktestRuns(8).catch(() => ({ ok: false, runs: [] })),
      ]);

      const names = normalizeStrategies(strategyPayload);
      setStrategies(names);
      setRuns(normalizeRuns(runPayload));

      if (!names.includes(config.strategy_name) && names[0]) {
        setConfig((current) => ({ ...current, strategy_name: names[0] }));
      }

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load backtest bootstrap");
    }
  }

  async function loadStrategyDetail(strategyName: string) {
    try {
      const payload = await fetchBacktestStrategyDetail(strategyName);
      setStrategyDetail(getStrategyObject(payload));
    } catch {
      setStrategyDetail(null);
    }
  }

  function update<K extends keyof BacktestRunConfig>(key: K, value: BacktestRunConfig[K]) {
    setConfig((current) => ({ ...current, [key]: value }));
  }

  function toggleTimeframe(timeframe: string) {
    setConfig((current) => {
      const exists = current.timeframes.includes(timeframe);
      const next = exists ? current.timeframes.filter((item) => item !== timeframe) : [...current.timeframes, timeframe];
      return { ...current, timeframes: next };
    });
  }

  const payload = useMemo<BacktestRunConfig>(() => {
    const symbols = symbolsText.split(",").map((value) => value.trim().toUpperCase()).filter(Boolean);
    return { ...config, symbols };
  }, [config, symbolsText]);

  const validation = useMemo(() => {
    const issues: string[] = [];
    if (!payload.strategy_name) issues.push("Strategy is required.");
    if (!payload.symbols.length) issues.push("At least one symbol is required.");
    if (!payload.timeframes.length) issues.push("At least one timeframe is required.");
    if (!payload.start_time || !payload.end_time) issues.push("Start and end dates are required.");
    if (payload.starting_capital <= 0) issues.push("Starting capital must be positive.");
    if (payload.risk_per_trade_pct <= 0) issues.push("Risk per trade must be positive.");
    if (payload.dataset_id <= 0 && payload.data_mode === "local_historical_dataset") issues.push("Dataset ID is required for local historical data.");
    return issues;
  }, [payload]);

  async function handleValidateConfig() {
    try {
      setValidatingConfig(true);
      setError(null);
      const response = await validateBacktestRunConfig(payload);
      setBackendValidation(response);
    } catch (err) {
      setBackendValidation(null);
      setError(err instanceof Error ? err.message : "Strategy validation failed");
    } finally {
      setValidatingConfig(false);
    }
  }

  async function handleRun() {
    if (validation.length > 0) return;
    try {
      setRunning(true);
      setError(null);
      setResult(null);
      setLastStartedAt(new Date());
      const validationResponse = await validateBacktestRunConfig(payload);
      setBackendValidation(validationResponse);
      if (validationResponse?.validation?.valid === false || validationResponse?.valid === false) {
        setError("Backtest configuration validation failed. Check the validation panel.");
        return;
      }

      const response = await runBacktest(payload);
      setResult(response);
      await loadBootstrap();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Backtest run failed");
    } finally {
      setRunning(false);
    }
  }

  const summary = result?.summary;
  const returnTone = (summary?.return_pct ?? 0) > 0 ? "good" : (summary?.return_pct ?? 0) < 0 ? "bad" : "neutral";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.28em] text-cyan-200/55">Phase 17</div>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Backtest Lab</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-white/50">
            Configure real historical dataset runs, launch the backtest engine, and inspect the first result summary.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-2xl border border-cyan-300/15 bg-cyan-400/10 px-4 py-2 text-sm text-cyan-100">
          <Database size={16} />
          Dataset #{config.dataset_id} · {config.data_mode}
        </div>
      </div>

      {error ? <div className="rounded-3xl border border-rose-400/20 bg-rose-500/10 p-4 text-sm text-rose-100">{error}</div> : null}

      <div className="grid gap-5 xl:grid-cols-[420px_1fr]">
        <Panel title="Run Configuration" subtitle="Production-parity defaults for dataset_id=1." icon={<SlidersHorizontal size={18} className="text-cyan-200" />}>
          <div className="space-y-5">
            <div className="grid gap-3">
              <Field label="Strategy">
                <select className={inputClass()} value={config.strategy_name} onChange={(event) => update("strategy_name", event.target.value)}>
                  {strategies.map((name) => (
                    <option key={name} value={name} className="bg-slate-950">{name}</option>
                  ))}
                </select>
              </Field>
              <Field label="Strategy version">
                <input className={inputClass()} value={config.strategy_version ?? ""} onChange={(event) => update("strategy_version", event.target.value)} />
              </Field>
              <Field label="Symbols" hint="Comma-separated symbols.">
                <input className={inputClass()} value={symbolsText} onChange={(event) => setSymbolsText(event.target.value)} />
              </Field>
            </div>

            <div>
              <div className="mb-2 text-xs font-medium uppercase tracking-[0.16em] text-white/40">Timeframes</div>
              <div className="flex flex-wrap gap-2">
                {TIMEFRAME_OPTIONS.map((timeframe) => {
                  const active = config.timeframes.includes(timeframe);
                  return (
                    <button
                      key={timeframe}
                      type="button"
                      onClick={() => toggleTimeframe(timeframe)}
                      className={`rounded-2xl border px-3 py-2 text-sm transition ${active ? "border-cyan-300/30 bg-cyan-400/15 text-cyan-100" : "border-white/10 bg-white/6 text-white/55 hover:bg-white/10"}`}
                    >
                      {timeframe}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Start date"><input className={inputClass()} value={config.start_time} onChange={(event) => update("start_time", event.target.value)} /></Field>
              <Field label="End date"><input className={inputClass()} value={config.end_time} onChange={(event) => update("end_time", event.target.value)} /></Field>
              <Field label="Starting capital"><input className={inputClass()} type="number" value={config.starting_capital} onChange={(event) => update("starting_capital", Number(event.target.value))} /></Field>
              <Field label="Max cycles"><input className={inputClass()} type="number" value={config.max_cycles} onChange={(event) => update("max_cycles", Number(event.target.value))} /></Field>
              <Field label="Risk / trade %"><input className={inputClass()} type="number" step="0.1" value={config.risk_per_trade_pct} onChange={(event) => update("risk_per_trade_pct", Number(event.target.value))} /></Field>
              <Field label="Position leverage"><input className={inputClass()} type="number" value={config.guardian_max_position_leverage} onChange={(event) => update("guardian_max_position_leverage", Number(event.target.value))} /></Field>
              <Field label="Maker fee bps"><input className={inputClass()} type="number" value={config.maker_fee_bps} onChange={(event) => update("maker_fee_bps", Number(event.target.value))} /></Field>
              <Field label="Taker fee bps"><input className={inputClass()} type="number" value={config.taker_fee_bps} onChange={(event) => update("taker_fee_bps", Number(event.target.value))} /></Field>
              <Field label="Limit fill ratio"><input className={inputClass()} type="number" step="0.05" value={config.limit_order_fill_ratio} onChange={(event) => update("limit_order_fill_ratio", Number(event.target.value))} /></Field>
              <Field label="Slippage bps"><input className={inputClass()} type="number" value={config.slippage_bps} onChange={(event) => update("slippage_bps", Number(event.target.value))} /></Field>
              <Field label="Spread bps" hint="UI-only until Phase 18 model."><input className={inputClass()} type="number" value={config.spread_bps ?? 0} onChange={(event) => update("spread_bps", Number(event.target.value))} /></Field>
              <Field label="Dataset ID"><input className={inputClass()} type="number" value={config.dataset_id} onChange={(event) => update("dataset_id", Number(event.target.value))} /></Field>
            </div>

            <div className="grid gap-3">
              <Field label="Execution simulation mode">
                <select className={inputClass()} value={config.execution_mode} onChange={(event) => update("execution_mode", event.target.value)}>
                  <option className="bg-slate-950" value="phase17_simple_fill_current_engine">Phase 17 current engine: simple fill + fee/slippage</option>
                  <option className="bg-slate-950" value="phase18_realistic_execution_pending">Phase 18 realistic execution pending</option>
                </select>
              </Field>
              <Field label="Macro bias mode">
                <select className={inputClass()} value={config.macro_bias_mode} onChange={(event) => update("macro_bias_mode", event.target.value)}>
                  <option className="bg-slate-950" value="strategy_default">Strategy default</option>
                  <option className="bg-slate-950" value="disabled">Disabled</option>
                  <option className="bg-slate-950" value="btc_macro_proxy">BTC macro proxy</option>
                </select>
              </Field>
              <Field label="Regime model version">
                <input className={inputClass()} value={config.regime_model_version} onChange={(event) => update("regime_model_version", event.target.value)} />
              </Field>
            </div>

            {validation.length ? (
              <div className="rounded-2xl border border-amber-300/20 bg-amber-400/10 p-3 text-sm text-amber-100">
                <div className="mb-1 flex items-center gap-2 font-medium"><AlertTriangle size={15} />Fix before running</div>
                <ul className="list-disc space-y-1 pl-5 text-amber-100/80">{validation.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
            ) : null}

            <button
              type="button"
              disabled={running || validation.length > 0}
              onClick={handleRun}
              className="flex w-full items-center justify-center gap-2 rounded-2xl border border-emerald-300/20 bg-emerald-500/15 px-4 py-3 text-sm font-semibold text-emerald-100 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {running ? <Loader2 size={17} className="animate-spin" /> : <Play size={17} />}
              {running ? "Running backtest..." : "Run backtest"}
            </button>
          </div>
        </Panel>

        <div className="space-y-5">
          <div className="grid gap-5 xl:grid-cols-2">
            <BacktestStrategyDetailPanel
              strategyName={config.strategy_name}
              detail={strategyDetail}
              selectedTimeframes={config.timeframes}
              dataMode={config.data_mode}
              datasetId={config.dataset_id}
              backendValidation={backendValidation}
            />

            <BacktestValidationPanel
              localIssues={validation}
              backendValidation={backendValidation}
              validating={validatingConfig}
              onValidate={handleValidateConfig}
            />

            <Panel title="Progress" subtitle="Synchronous backend run for now." icon={<Zap size={18} className="text-yellow-200" />}>
              <div className="space-y-4">
                <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm text-white/45">Current status</div>
                      <div className="mt-1 text-xl font-semibold text-white">{running ? "Running" : result?.ok ? "Completed" : "Idle"}</div>
                    </div>
                    {running ? <Loader2 className="animate-spin text-cyan-200" /> : <ShieldCheck className="text-emerald-200" />}
                  </div>
                  <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10">
                    <div className={`h-full rounded-full ${running ? "w-2/3 animate-pulse bg-cyan-300" : result ? "w-full bg-emerald-300" : "w-0 bg-white/30"}`} />
                  </div>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <MetricTile label="Cycles processed" value={String(result?.diagnostics?.cycle_count ?? "—")} />
                  <MetricTile label="Trades generated" value={String(result?.summary?.total_trades ?? "—")} />
                  <MetricTile label="Candles processed" value="—" />
                  <MetricTile label="Simulated date" value={textValue(result?.preflight?.end_time ?? result?.diagnostics?.preflight?.end_time)} />
                </div>
                <div className="rounded-2xl border border-white/10 bg-black/20 p-4 text-sm text-white/50">
                  Cancel/progress streaming requires an async backend endpoint. Current `/backtests/run` blocks until completion.
                  Started: {lastStartedAt ? ` ${lastStartedAt.toLocaleString()}` : " —"}
                </div>
              </div>
            </Panel>
          </div>

          <Panel title="Results" subtitle="Core metrics already returned by backtest-engine." icon={<BarChart3 size={18} className="text-emerald-200" />}>
            {summary ? (
              <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
                <MetricTile label="Final equity" value={money(summary.final_equity)} />
                <MetricTile label="Return" value={pct(summary.return_pct)} tone={returnTone} />
                <MetricTile label="Gross PnL" value={money(summary.gross_pnl)} tone={(summary.gross_pnl ?? 0) >= 0 ? "good" : "bad"} />
                <MetricTile label="Net PnL" value={money(summary.net_pnl)} tone={(summary.net_pnl ?? 0) >= 0 ? "good" : "bad"} />
                <MetricTile label="Max DD" value={pct(summary.max_drawdown_pct)} tone="bad" />
                <MetricTile label="Trades" value={String(summary.total_trades ?? "—")} />
                <MetricTile label="Win rate" value={summary.win_rate === null || summary.win_rate === undefined ? "—" : pct(summary.win_rate * 100)} />
                <MetricTile label="Profit factor" value={numberFmt(summary.profit_factor)} />
                <MetricTile label="Sharpe" value="Not calculated" />
                <MetricTile label="Sortino" value="Not calculated" />
                <MetricTile label="Expectancy" value="Not calculated" />
                <MetricTile label="Avg R" value="Not calculated" />
              </div>
            ) : (
              <div className="rounded-2xl border border-white/10 bg-black/20 p-6 text-center text-sm text-white/45">
                No run result yet. Configure the run and press <span className="text-white/70">Run backtest</span>.
              </div>
            )}
          </Panel>

          <Panel title="Recent Runs" subtitle="Quick visibility before full result browser/charts in 17F-17H." icon={<CalendarDays size={18} className="text-cyan-200" />}>
            <div className="overflow-hidden rounded-2xl border border-white/10">
              <table className="min-w-full divide-y divide-white/10 text-sm">
                <thead className="bg-white/5 text-left text-xs uppercase tracking-[0.16em] text-white/35">
                  <tr>
                    <th className="px-4 py-3">Run</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Strategy</th>
                    <th className="px-4 py-3">Return</th>
                    <th className="px-4 py-3">Trades</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/8 text-white/65">
                  {runs.length ? runs.map((run, index) => (
                    <tr key={run.run_id ?? index}>
                      <td className="px-4 py-3 text-white">#{run.run_id ?? "—"}</td>
                      <td className="px-4 py-3">{textValue(run.status)}</td>
                      <td className="px-4 py-3">{textValue(run.strategy_name)}</td>
                      <td className="px-4 py-3">{pct(typeof run.return_pct === "number" ? run.return_pct : undefined)}</td>
                      <td className="px-4 py-3">{textValue(run.total_trades)}</td>
                    </tr>
                  )) : (
                    <tr>
                      <td className="px-4 py-6 text-center text-white/40" colSpan={5}>No recent runs loaded.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      </div>

      <Panel title="Phase 17 roadmap preview" icon={<RefreshCcw size={18} className="text-white/60" />}>
        <div className="grid gap-3 md:grid-cols-5">
          {["17D Strategy detail polish", "17E async progress", "17F full metrics", "17G charts", "17H trades/logs/debug"].map((item) => (
            <div key={item} className="rounded-2xl border border-white/10 bg-black/18 p-4 text-sm text-white/55">{item}</div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
