export function money(value: number | null | undefined) {
  const n = value ?? 0;
  return `$${n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function metricNumber(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "-";
  return value.toFixed(digits);
}

export function signedClass(value: number | null | undefined) {
  const n = value ?? 0;
  if (n > 0) return "text-emerald-300";
  if (n < 0) return "text-rose-300";
  return "text-white";
}

export function hasMeaningfulSeries(
  values: Array<Record<string, unknown>>,
  key: string
) {
  return values.some((v) => {
    const value = v[key];
    return typeof value === "number" && Math.abs(value) > 0;
  });
}

export function monthLabel(monthKey: string | null | undefined) {
  if (!monthKey) return "-";
  const [year, month] = monthKey.split("-");
  const d = new Date(Number(year), Number(month) - 1, 1);
  return d.toLocaleString(undefined, { month: "long", year: "numeric" });
}