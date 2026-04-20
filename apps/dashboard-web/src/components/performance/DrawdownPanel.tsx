import {
  AreaChart,
  Area,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { DrawdownPoint } from "../../types/performance";
import ChartCard from "./ChartCard";
import { money, hasMeaningfulSeries } from "../../lib/performance";
import type { Formatter, NameType, ValueType } from "recharts/types/component/DefaultTooltipContent";

const drawdownTooltipFormatter: Formatter<ValueType, NameType> = (value, name) => {
  const numericValue = Number(value) || 0;

  const displayValue = name === "drawdown_pct"
    ? `${numericValue.toFixed(2)}%`
    : money(numericValue);

  return [displayValue, name];
};

export default function DrawdownPanel({
  items,
}: {
  items: DrawdownPoint[];
}) {
  const hasData = items.length > 0 && hasMeaningfulSeries(items, "drawdown_value");

  return (
    <ChartCard
      title="Drawdown Curve"
      subtitle="Underwater path from peak equity"
      right={hasData ? `Points ${items.length}` : "Flat / no drawdown yet"}
    >
      {!hasData ? (
        <div className="flex h-[280px] items-center justify-center rounded-2xl border border-white/8 bg-white/5">
          <div className="text-center">
            <div className="text-sm font-medium text-white/70">No drawdown recorded</div>
            <div className="mt-2 text-sm text-white/45">
              Equity has not fallen below a prior peak yet.
            </div>
          </div>
        </div>
      ) : (
        <div className="h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={items}>
              <CartesianGrid stroke="rgba(255,255,255,0.07)" vertical={false} />
              <XAxis
                dataKey="recorded_at"
                tickFormatter={(v) => new Date(v).toLocaleDateString()}
                tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 12 }}
              />
              <YAxis tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 12 }} />
              <Tooltip
                formatter={drawdownTooltipFormatter}
                labelFormatter={(label) => new Date(label).toLocaleString()}
                contentStyle={{
                  background: "rgba(14, 17, 30, 0.9)",
                  border: "1px solid rgba(255,255,255,0.08)",
                  borderRadius: "16px",
                }}
              />
              <Area
                type="monotone"
                dataKey="drawdown_value"
                stroke="rgba(244,114,182,0.95)"
                fill="rgba(244,114,182,0.18)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}