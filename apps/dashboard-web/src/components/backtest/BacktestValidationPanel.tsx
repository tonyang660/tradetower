import { AlertTriangle, CheckCircle2, Loader2, ShieldCheck } from "lucide-react";

function asArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function validFrom(payload: any): boolean | null {
  if (!payload) return null;
  if (typeof payload.valid === "boolean") return payload.valid;
  if (typeof payload.validation?.valid === "boolean") return payload.validation.valid;
  if (typeof payload.ok === "boolean" && payload.validation) return payload.ok;
  return null;
}

function errorsFrom(payload: any): string[] {
  return [...asArray(payload?.errors), ...asArray(payload?.validation?.errors)];
}

function warningsFrom(payload: any): string[] {
  return [...asArray(payload?.warnings), ...asArray(payload?.validation?.warnings)];
}

function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "good" | "bad" | "warn" }) {
  const cls =
    tone === "good"
      ? "border-emerald-300/20 bg-emerald-500/10 text-emerald-100"
      : tone === "bad"
      ? "border-rose-300/20 bg-rose-500/10 text-rose-100"
      : tone === "warn"
      ? "border-amber-300/20 bg-amber-500/10 text-amber-100"
      : "border-white/10 bg-white/8 text-white/60";
  return <span className={`rounded-full border px-2.5 py-1 text-xs ${cls}`}>{children}</span>;
}

export default function BacktestValidationPanel({
  localIssues,
  backendValidation,
  validating,
  onValidate,
}: {
  localIssues: string[];
  backendValidation: any;
  validating: boolean;
  onValidate: () => void;
}) {
  const backendValid = validFrom(backendValidation);
  const errors = errorsFrom(backendValidation);
  const warnings = warningsFrom(backendValidation);
  const requestedTimeframes = backendValidation?.validation?.requested_timeframes ?? [];
  const requiredTimeframes = backendValidation?.validation?.required_timeframes ?? [];
  const strict = backendValidation?.validation?.strict_timeframes;

  return (
    <section className="rounded-[28px] border border-white/10 bg-white/6 p-5 shadow-glass backdrop-blur-xl">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-lg font-semibold tracking-tight text-white">
            <ShieldCheck size={18} className="text-emerald-200" />
            Configuration Validation
          </div>
          <div className="mt-1 text-sm text-white/45">Local form checks plus backend strategy validation.</div>
        </div>
        <button
          type="button"
          onClick={onValidate}
          disabled={validating}
          className="inline-flex items-center gap-2 rounded-2xl border border-cyan-300/20 bg-cyan-500/10 px-3 py-2 text-sm font-medium text-cyan-100 transition hover:bg-cyan-500/15 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {validating ? <Loader2 size={15} className="animate-spin" /> : <ShieldCheck size={15} />}
          Validate
        </button>
      </div>

      <div className="space-y-3">
        <div className="flex flex-wrap gap-2">
          {localIssues.length === 0 ? <Pill tone="good">Local form OK</Pill> : <Pill tone="warn">{localIssues.length} local issue(s)</Pill>}
          {backendValid === true ? <Pill tone="good">Backend valid</Pill> : backendValid === false ? <Pill tone="bad">Backend invalid</Pill> : <Pill>Backend not checked</Pill>}
          {strict ? <Pill tone="warn">Strict timeframes</Pill> : <Pill>Flexible timeframes</Pill>}
        </div>

        {requestedTimeframes.length || requiredTimeframes.length ? (
          <div className="rounded-2xl border border-white/10 bg-black/18 p-4 text-sm">
            <div className="grid gap-2 md:grid-cols-2">
              <div><span className="text-white/40">Requested:</span> <span className="text-white">{requestedTimeframes.join(", ") || "—"}</span></div>
              <div><span className="text-white/40">Required:</span> <span className="text-white">{requiredTimeframes.join(", ") || "—"}</span></div>
            </div>
          </div>
        ) : null}

        {localIssues.length ? (
          <div className="rounded-2xl border border-amber-300/20 bg-amber-500/10 p-4 text-sm text-amber-100">
            <div className="mb-2 flex items-center gap-2 font-medium"><AlertTriangle size={15} />Local issues</div>
            <ul className="list-disc space-y-1 pl-5 text-amber-100/80">{localIssues.map((issue) => <li key={issue}>{issue}</li>)}</ul>
          </div>
        ) : null}

        {errors.length ? (
          <div className="rounded-2xl border border-rose-300/20 bg-rose-500/10 p-4 text-sm text-rose-100">
            <div className="mb-2 flex items-center gap-2 font-medium"><AlertTriangle size={15} />Backend errors</div>
            <ul className="list-disc space-y-1 pl-5 text-rose-100/80">{errors.map((issue) => <li key={issue}>{issue}</li>)}</ul>
          </div>
        ) : null}

        {warnings.length ? (
          <div className="rounded-2xl border border-amber-300/20 bg-amber-500/10 p-4 text-sm text-amber-100">
            <div className="mb-2 flex items-center gap-2 font-medium"><AlertTriangle size={15} />Backend warnings</div>
            <ul className="list-disc space-y-1 pl-5 text-amber-100/80">{warnings.map((issue) => <li key={issue}>{issue}</li>)}</ul>
          </div>
        ) : null}

        {backendValid === true && !warnings.length ? (
          <div className="rounded-2xl border border-emerald-300/20 bg-emerald-500/10 p-4 text-sm text-emerald-100">
            <div className="flex items-center gap-2 font-medium"><CheckCircle2 size={15} />Configuration is ready to run.</div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
