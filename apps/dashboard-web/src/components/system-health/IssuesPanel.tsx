import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";
import type { SystemHealthIssue } from "../../types/systemHealth";

function issueTone(level: SystemHealthIssue["level"]) {
  if (level === "critical") {
    return "border-rose-400/15 bg-rose-500/10 text-rose-200";
  }
  if (level === "warning") {
    return "border-amber-400/15 bg-amber-500/10 text-amber-200";
  }
  return "border-cyan-400/15 bg-cyan-500/10 text-cyan-200";
}

export default function IssuesPanel({
  issues,
}: {
  issues: SystemHealthIssue[];
}) {
  return (
    <GlassCard>
      <SectionTitle
        title="Active Issues"
        subtitle="Detected service anomalies and reliability warnings"
      />

      <div className="mt-5 space-y-3">
        {issues.length === 0 ? (
          <div className="rounded-[24px] border border-emerald-400/12 bg-emerald-500/8 p-4 text-sm text-emerald-200">
            No active incidents detected.
          </div>
        ) : (
          issues.map((issue, idx) => (
            <div
              key={`${issue.code}-${idx}`}
              className="rounded-[24px] border border-white/8 bg-white/5 p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-base font-semibold text-white">{issue.title}</div>
                  <div className="mt-1 text-sm text-white/50">{issue.detail}</div>
                </div>

                <div className={`rounded-full border px-2.5 py-1 text-xs ${issueTone(issue.level)}`}>
                  {issue.level.toUpperCase()}
                </div>
              </div>

              <div className="mt-3 text-xs text-white/35">
                {new Date(issue.detected_at).toLocaleString()}
              </div>
            </div>
          ))
        )}
      </div>
    </GlassCard>
  );
}