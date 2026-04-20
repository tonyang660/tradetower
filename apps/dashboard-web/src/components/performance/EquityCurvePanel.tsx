import {
  LineChart,
  Line,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { EquityPoint } from "../../types/performance";
import ChartCard from "./ChartCard";
import { money, hasMeaningfulSeries } from "../../lib/performance";

export default function EquityCurvePanel({
  items,
}: {
  items: EquityPoint[];
}) {
  const hasData = items.length > 0 && hasMeaningfulSeries(items, "equity");

  return (
    <ChartCard
      title="Equity Curve"
      subtitle="Account equity over recorded updates"
      right={hasData ? `Points ${items.length}` : "No live history yet"}
    >
      {!hasData ? (
        <div className="rounded-2xl border border-white/8 bg-white/5 p-6 text-sm text-white/50">
          Equity history will appear here as live snapshots accumulate.
        </div>
      ) : (
        <div className="h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={items}>
              <CartesianGrid stroke="rgba(255,255,255,0.07)" vertical={false} />
              <XAxis
                dataKey="recorded_at"
                tickFormatter={(v) => new Date(v).toLocaleDateString()}
                tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 12 }}
              />
              <YAxis tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 12 }} />
              <Tooltip
                formatter={(value: unknown) => {
                  const numericValue =
                    typeof value === "number"
                      ? value
                      : typeof value === "string"
                      ? Number(value)
                      : 0;

                  return money(numericValue);
                }}
                labelFormatter={(label) => new Date(label).toLocaleString()}
                contentStyle={{
                  background: "rgba(14, 17, 30, 0.9)",
                  border: "1px solid rgba(255,255,255,0.08)",
                  borderRadius: "16px",
                }}
              />
              <Line type="monotone" dataKey="equity" stroke="rgba(168,85,247,0.95)" strokeWidth={2.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}