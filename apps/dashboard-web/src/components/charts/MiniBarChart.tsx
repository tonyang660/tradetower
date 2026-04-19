import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export default function MiniBarChart({
  data,
}: {
  data: { label: string; value: number }[];
}) {
  return (
    <div className="h-[180px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "rgba(255,255,255,0.35)", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            allowDecimals={false}
          />
          <Tooltip
            contentStyle={{
              background: "rgba(12,16,30,0.92)",
              border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 16,
              color: "#fff",
            }}
          />
          <Bar dataKey="value" radius={[8, 8, 0, 0]} fill="rgba(167,139,250,0.9)" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}