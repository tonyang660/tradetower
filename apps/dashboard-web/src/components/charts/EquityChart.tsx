import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export default function EquityChart({
  data,
}: {
  data: { recorded_at: string; equity: number }[];
}) {
  return (
    <div className="h-[300px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <defs>
            <linearGradient id="equityFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="rgba(168,85,247,0.55)" />
              <stop offset="100%" stopColor="rgba(168,85,247,0.02)" />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis
            dataKey="recorded_at"
            tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 12 }}
            tickFormatter={(value) => new Date(value).toLocaleDateString()}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            domain={["auto", "auto"]}
          />
          <Tooltip
            contentStyle={{
              background: "rgba(12,16,30,0.92)",
              border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 16,
              color: "#fff",
            }}
            labelFormatter={(value) => new Date(String(value)).toLocaleString()}
          />
          <Area
            type="monotone"
            dataKey="equity"
            stroke="#a78bfa"
            strokeWidth={2}
            fill="url(#equityFill)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
