import { useEffect, useMemo, useState } from "react";
import { Activity, FileJson, Layers3, ListChecks, RefreshCcw, ScrollText } from "lucide-react";
import {
  fetchBacktestExitLegs,
  fetchBacktestLogs,
  fetchBacktestPositionEvents,
  fetchBacktestPositions,
  fetchBacktestResultBundle,
} from "../../lib/backtestApi";

type InspectorTab = "positions" | "exit_legs" | "position_events" | "logs" | "bundle";

function money(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function textValue(value: unknown, fallback = "—") {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function first(row: any, keys: string[], fallback: unknown = null) {
  for (const key of keys) {
    if (row && row[key] !== undefined && row[key] !== null) return row[key];
  }
  return fallback;
}

function pnlTone(value: unknown) {
  if (typeof value !== "number") return "text-white/65";
  if (value > 0) return "text-emerald-200";
  if (value < 0) return "text-rose-200";
  return "text-white/65";
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-2xl border px-3 py-2 text-sm transition ${
        active
          ? "border-cyan-300/30 bg-cyan-400/15 text-cyan-100"
          : "border-white/10 bg-white/6 text-white/55 hover:bg-white/10"
      }`}
    >
      {children}
    </button>
  );
}

export default function BacktestRunInspector({ runId }: { runId: number | null | undefined }) {
  const [tab, setTab] = useState<InspectorTab>("positions");
  const [positions, setPositions] = useState<any[]>([]);
  const [exitLegs, setExitLegs] = useState<any[]>([]);
  const [positionEvents, setPositionEvents] = useState<any[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [bundle, setBundle] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    if (!runId) return;

    try {
      setLoading(true);
      setError(null);

      if (tab === "positions") {
        const payload = await fetchBacktestPositions(runId, 250);
        setPositions(payload.positions ?? payload.rows ?? []);
      } else if (tab === "exit_legs") {
        const payload = await fetchBacktestExitLegs(runId, 250);
        setExitLegs(payload.exit_legs ?? payload.rows ?? []);
      } else if (tab === "position_events") {
        const payload = await fetchBacktestPositionEvents(runId, 1000);
        setPositionEvents(payload.position_events ?? payload.rows ?? []);
      } else if (tab === "logs") {
        const payload = await fetchBacktestLogs(runId, 250);
        setLogs(payload.logs ?? payload.rows ?? []);
      } else {
        const payload = await fetchBacktestResultBundle(runId);
        setBundle(payload);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load run details");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, tab]);

  const bundlePreview = useMemo(() => {
    if (!bundle) return "";
    return JSON.stringify(bundle, null, 2);
  }, [bundle]);

  if (!runId) {
    return (
      <section className="rounded-[28px] border border-white/10 bg-white/6 p-5 shadow-glass backdrop-blur-xl">
        <div className="flex items-center gap-2 text-lg font-semibold tracking-tight text-white">
          <ListChecks size={18} className="text-cyan-200" />
          Run Inspector
        </div>
        <div className="mt-4 rounded-2xl border border-white/10 bg-black/20 p-6 text-center text-sm text-white/40">
          Run or select a backtest to inspect positions, exit legs, lifecycle events, logs, and raw output.
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-[28px] border border-white/10 bg-white/6 p-5 shadow-glass backdrop-blur-xl">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-lg font-semibold tracking-tight text-white">
            <ListChecks size={18} className="text-cyan-200" />
            Run Inspector
          </div>
          <div className="mt-1 text-sm text-white/45">Positions, exit legs, lifecycle events, logs, and raw output for run #{runId}.</div>
        </div>

        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-2xl border border-white/10 bg-white/8 px-3 py-2 text-sm text-white/70 transition hover:bg-white/12 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        <TabButton active={tab === "positions"} onClick={() => setTab("positions")}>
          <Layers3 size={14} className="mr-1 inline" />
          Positions
        </TabButton>
        <TabButton active={tab === "exit_legs"} onClick={() => setTab("exit_legs")}>
          <ListChecks size={14} className="mr-1 inline" />
          Exit legs
        </TabButton>
        <TabButton active={tab === "position_events"} onClick={() => setTab("position_events")}>
          <Activity size={14} className="mr-1 inline" />
          Lifecycle
        </TabButton>
        <TabButton active={tab === "logs"} onClick={() => setTab("logs")}>
          <ScrollText size={14} className="mr-1 inline" />
          Logs
        </TabButton>
        <TabButton active={tab === "bundle"} onClick={() => setTab("bundle")}>
          <FileJson size={14} className="mr-1 inline" />
          Result bundle
        </TabButton>
      </div>

      {error ? <div className="mb-4 rounded-2xl border border-rose-300/20 bg-rose-500/10 p-4 text-sm text-rose-100">{error}</div> : null}

      {tab === "positions" ? (
        <div className="overflow-x-auto rounded-2xl border border-white/10">
          <table className="min-w-full divide-y divide-white/10 text-sm">
            <thead className="bg-white/5 text-left text-xs uppercase tracking-[0.16em] text-white/35">
              <tr>
                <th className="px-4 py-3">Position</th>
                <th className="px-4 py-3">Symbol</th>
                <th className="px-4 py-3">Side</th>
                <th className="px-4 py-3">Opened</th>
                <th className="px-4 py-3">Closed</th>
                <th className="px-4 py-3">Realized PnL</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Close reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/8 text-white/65">
              {positions.length ? positions.map((position, index) => {
                const pnl = first(position, ["realized_pnl", "net_pnl", "pnl"], null);
                return (
                  <tr key={first(position, ["position_id"], index)}>
                    <td className="px-4 py-3 text-white">{textValue(first(position, ["position_id"]))}</td>
                    <td className="px-4 py-3 text-white">{textValue(first(position, ["symbol"]))}</td>
                    <td className="px-4 py-3">{textValue(first(position, ["side"]))}</td>
                    <td className="px-4 py-3">{textValue(first(position, ["opened_at", "entry_time", "created_at"]))}</td>
                    <td className="px-4 py-3">{textValue(first(position, ["closed_at", "exit_time", "updated_at"]))}</td>
                    <td className={`px-4 py-3 ${pnlTone(pnl)}`}>{money(pnl)}</td>
                    <td className="px-4 py-3">{textValue(first(position, ["status"]))}</td>
                    <td className="px-4 py-3">{textValue(first(position, ["close_reason", "exit_reason", "reason"]))}</td>
                  </tr>
                );
              }) : (
                <tr><td className="px-4 py-6 text-center text-white/35" colSpan={8}>{loading ? "Loading positions..." : "No positions found."}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      ) : null}

      {tab === "exit_legs" ? (
        <div className="overflow-x-auto rounded-2xl border border-white/10">
          <table className="min-w-full divide-y divide-white/10 text-sm">
            <thead className="bg-white/5 text-left text-xs uppercase tracking-[0.16em] text-white/35">
              <tr>
                <th className="px-4 py-3">Position</th>
                <th className="px-4 py-3">Symbol</th>
                <th className="px-4 py-3">Side</th>
                <th className="px-4 py-3">Entry</th>
                <th className="px-4 py-3">Exit</th>
                <th className="px-4 py-3">Net PnL</th>
                <th className="px-4 py-3">Fees</th>
                <th className="px-4 py-3">Regime</th>
                <th className="px-4 py-3">Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/8 text-white/65">
              {exitLegs.length ? exitLegs.map((leg, index) => {
                const net = first(leg, ["net_pnl", "pnl_net", "realized_pnl", "pnl"], null);
                const fees = first(leg, ["fees", "total_fees"], null);
                return (
                  <tr key={first(leg, ["trade_id"], index)}>
                    <td className="px-4 py-3">{textValue(first(leg, ["position_id"]))}</td>
                    <td className="px-4 py-3 text-white">{textValue(first(leg, ["symbol"]))}</td>
                    <td className="px-4 py-3">{textValue(first(leg, ["side"]))}</td>
                    <td className="px-4 py-3">{textValue(first(leg, ["entry_time", "opened_at", "created_at"]))}</td>
                    <td className="px-4 py-3">{textValue(first(leg, ["exit_time", "closed_at", "completed_at"]))}</td>
                    <td className={`px-4 py-3 ${pnlTone(net)}`}>{money(net)}</td>
                    <td className="px-4 py-3">{money(fees)}</td>
                    <td className="px-4 py-3">{textValue(first(leg, ["regime", "market_regime", "strategy_route"]))}</td>
                    <td className="px-4 py-3">{textValue(first(leg, ["exit_reason", "reason", "close_reason"]))}</td>
                  </tr>
                );
              }) : (
                <tr><td className="px-4 py-6 text-center text-white/35" colSpan={9}>{loading ? "Loading exit legs..." : "No exit legs found."}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      ) : null}

      {tab === "position_events" ? (
        <div className="overflow-x-auto rounded-2xl border border-white/10">
          <table className="min-w-full divide-y divide-white/10 text-sm">
            <thead className="bg-white/5 text-left text-xs uppercase tracking-[0.16em] text-white/35">
              <tr>
                <th className="px-4 py-3">Position</th>
                <th className="px-4 py-3">Seq</th>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Event</th>
                <th className="px-4 py-3">Price</th>
                <th className="px-4 py-3">Quantity</th>
                <th className="px-4 py-3">Remaining</th>
                <th className="px-4 py-3">Realized PnL</th>
                <th className="px-4 py-3">Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/8 text-white/65">
              {positionEvents.length ? positionEvents.map((event, index) => {
                const pnl = first(event, ["realized_pnl", "net_pnl", "pnl"], null);
                return (
                  <tr key={first(event, ["position_event_id", "event_id"], index)}>
                    <td className="px-4 py-3 text-white">{textValue(first(event, ["position_id"]))}</td>
                    <td className="px-4 py-3">{textValue(first(event, ["sequence_index", "event_sequence", "sequence_no", "sequence"]))}</td>
                    <td className="px-4 py-3">{textValue(first(event, ["event_time", "timestamp", "created_at"]))}</td>
                    <td className="px-4 py-3 text-cyan-100">{textValue(first(event, ["event_type", "type"]))}</td>
                    <td className="px-4 py-3">{textValue(first(event, ["price", "fill_price", "exit_price"]))}</td>
                    <td className="px-4 py-3">{textValue(first(event, ["quantity", "qty", "fill_quantity"]))}</td>
                    <td className="px-4 py-3">{textValue(first(event, ["remaining_size", "remaining_quantity", "remaining_qty"]))}</td>
                    <td className={`px-4 py-3 ${pnlTone(pnl)}`}>{money(pnl)}</td>
                    <td className="px-4 py-3">{textValue(first(event, ["reason", "exit_reason", "trigger_type"]))}</td>
                  </tr>
                );
              }) : (
                <tr><td className="px-4 py-6 text-center text-white/35" colSpan={9}>{loading ? "Loading lifecycle events..." : "No lifecycle events found."}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      ) : null}

      {tab === "logs" ? (
        <div className="max-h-[520px] space-y-2 overflow-auto rounded-2xl border border-white/10 bg-black/18 p-3">
          {logs.length ? logs.map((log, index) => (
            <div key={first(log, ["log_id"], index)} className="rounded-xl border border-white/8 bg-white/5 p-3 text-xs text-white/55">
              <span className="text-white/35">{textValue(first(log, ["timestamp", "created_at"]))}</span>
              <span className="mx-2 text-white/25">·</span>
              <span className="text-white/75">{textValue(first(log, ["event_type", "level", "type"]))}</span>
              <span className="mx-2 text-white/25">·</span>
              <span>{textValue(first(log, ["message", "msg"]))}</span>
            </div>
          )) : <div className="p-6 text-center text-sm text-white/35">{loading ? "Loading logs..." : "No logs found."}</div>}
        </div>
      ) : null}

      {tab === "bundle" ? (
        <div className="rounded-2xl border border-white/10 bg-black/30 p-4">
          {bundlePreview ? (
            <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap text-xs leading-5 text-white/60">{bundlePreview}</pre>
          ) : (
            <div className="p-6 text-center text-sm text-white/35">{loading ? "Loading bundle..." : "No bundle loaded."}</div>
          )}
        </div>
      ) : null}
    </section>
  );
}
