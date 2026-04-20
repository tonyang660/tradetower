import {
  BarChart,
  Bar,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import ChartCard from "./ChartCard";
import { money, hasMeaningfulSeries } from "../../lib/performance";
import type { Formatter, NameType, ValueType } from "recharts/types/component/DefaultTooltipContent";

const pnlTooltipFormatter: Formatter<ValueType, NameType> = (value, name) => {
  const numericValue = Number(value) || 0;

  const displayValue = name === "pnl" 
    ? money(numericValue) 
    : String(value ?? "");

  return [displayValue, name];
};

export default function MetricBarChartPanel<T extends Record<string, any>>({
  title,
  subtitle,
  data,
  xKey,
  pnlKey = "pnl",
  rightLabel,
}: {
  title: string;
  subtitle: string;
  data: T[];
  xKey: keyof T;
  pnlKey?: keyof T;
  rightLabel?: string;
}) {
  const hasData = data.length > 0 && hasMeaningfulSeries(data as any, pnlKey as string);

  return (
    <ChartCard title={title} subtitle={subtitle} right={rightLabel}>
      {!hasData ? (
        <div className="rounded-2xl border border-white/8 bg-white/5 p-6 text-sm text-white/50">
          This chart will populate once closed-trade performance data exists.
        </div>
      ) : (
        <div className="h-[260px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data}>
              <CartesianGrid stroke="rgba(255,255,255,0.07)" vertical={false} />
              <XAxis dataKey={xKey as string} tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 12 }} />
              <YAxis tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 12 }} />
              <Tooltip
                formatter={pnlTooltipFormatter}
                contentStyle={{
                  background: "rgba(14, 17, 30, 0.9)",
                  border: "1px solid rgba(255,255,255,0.08)",
                  borderRadius: "16px",
                }}
              />
              <Bar dataKey={pnlKey as string} fill="rgba(168,85,247,0.8)" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </ChartCard>
  );
}