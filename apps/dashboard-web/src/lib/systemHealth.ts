import type { HealthStatus, OverallStatus } from "../types/systemHealth";

export function formatLatency(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "-";
  return `${value.toFixed(1)} ms`;
}

export function formatRelativeAge(seconds: number | null | undefined) {
  if (seconds == null || Number.isNaN(seconds)) return "-";

  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

export function statusTone(status: HealthStatus) {
  if (status === "healthy") {
    return {
      dot: "bg-emerald-400",
      pill: "border-emerald-400/15 bg-emerald-500/10 text-emerald-200",
      glow: "shadow-[0_0_30px_rgba(16,185,129,0.18)]",
    };
  }

  if (status === "degraded") {
    return {
      dot: "bg-amber-400",
      pill: "border-amber-400/15 bg-amber-500/10 text-amber-200",
      glow: "shadow-[0_0_30px_rgba(251,191,36,0.18)]",
    };
  }

  if (status === "offline") {
    return {
      dot: "bg-rose-400",
      pill: "border-rose-400/15 bg-rose-500/10 text-rose-200",
      glow: "shadow-[0_0_30px_rgba(244,63,94,0.2)]",
    };
  }

  return {
    dot: "bg-white/30",
    pill: "border-white/10 bg-white/5 text-white/65",
    glow: "",
  };
}

export function overallTone(status: OverallStatus) {
  if (status === "operational") {
    return {
      beacon: "bg-emerald-400 shadow-[0_0_40px_rgba(16,185,129,0.45)]",
      text: "text-emerald-200",
      pill: "border-emerald-400/15 bg-emerald-500/10 text-emerald-200",
    };
  }

  if (status === "degraded") {
    return {
      beacon: "bg-amber-400 shadow-[0_0_40px_rgba(251,191,36,0.4)]",
      text: "text-amber-200",
      pill: "border-amber-400/15 bg-amber-500/10 text-amber-200",
    };
  }

  if (status === "partial_outage" || status === "offline") {
    return {
      beacon: "bg-rose-400 shadow-[0_0_40px_rgba(244,63,94,0.45)]",
      text: "text-rose-200",
      pill: "border-rose-400/15 bg-rose-500/10 text-rose-200",
    };
  }

  return {
    beacon: "bg-white/40",
    text: "text-white",
    pill: "border-white/10 bg-white/5 text-white/70",
  };
}

export function titleCaseStatus(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}