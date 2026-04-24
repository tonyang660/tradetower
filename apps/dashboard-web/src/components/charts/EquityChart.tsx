import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type EquityPoint = {
  recorded_at: string;
  equity: number;
};

type RangeKey = "1H" | "4H" | "1D" | "1W" | "1M";

const RANGE_OPTIONS: RangeKey[] = ["1H", "4H", "1D", "1W", "1M"];

function getRangeMs(range: RangeKey) {
  switch (range) {
    case "1H":
      return 60 * 60 * 1000;
    case "4H":
      return 4 * 60 * 60 * 1000;
    case "1D":
      return 24 * 60 * 60 * 1000;
    case "1W":
      return 7 * 24 * 60 * 60 * 1000;
    case "1M":
      return 30 * 24 * 60 * 60 * 1000;
    default:
      return 24 * 60 * 60 * 1000;
  }
}

function formatXAxis(value: string, range: RangeKey) {
  const d = new Date(value);

  if (range === "1H" || range === "4H") {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  if (range === "1D") {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function formatTooltipLabel(value: string, range: RangeKey) {
  const d = new Date(value);

  if (range === "1H" || range === "4H" || range === "1D") {
    return d.toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatMoney(value: number) {
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export default function EquityChart({
  data,
}: {
  data: EquityPoint[];
}) {
  const [range, setRange] = useState<RangeKey>("1D");

  const filteredData = useMemo(() => {
    if (!data.length) return [];

    const lastTs = new Date(data[data.length - 1].recorded_at).getTime();
    const cutoff = lastTs - getRangeMs(range);

    const sliced = data.filter(
      (point) => new Date(point.recorded_at).getTime() >= cutoff
    );

    return sliced.length > 0 ? sliced : data.slice(-1);
  }, [data, range]);

  const yDomain = useMemo(() => {
    if (!filteredData.length) return [0, 1];

    const values = filteredData.map((d) => d.equity);
    const min = Math.min(...values);
    const max = Math.max(...values);

    if (min === max) {
      return [min - 2, max + 2];
    }

    const padding = Math.max((max - min) * 0.15, 1);
    return [min - padding, max + padding];
  }, [filteredData]);

  return (
    <div className="w-full">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2 rounded-2xl border border-white/8 bg-white/5 p-1">
          {RANGE_OPTIONS.map((option) => {
            const active = option === range;
            return (
              <button
                key={option}
                onClick={() => setRange(option)}
                className={`rounded-xl px-3 py-1.5 text-xs font-medium transition ${
                  active
                    ? "bg-violet-500/15 text-violet-200"
                    : "text-white/55 hover:bg-white/8 hover:text-white"
                }`}
              >
                {option}
              </button>
            );
          })}
        </div>
      </div>

      <div className="h-[420px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart
            data={filteredData}
            margin={{ top: 8, right: 8, left: -12, bottom: 8 }}
          >
            <defs>
              <linearGradient id="equityFill" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="#a855f7" stopOpacity={0.35} />
                <stop offset="65%" stopColor="#7c3aed" stopOpacity={0.12} />
                <stop offset="100%" stopColor="#7c3aed" stopOpacity={0.02} />
              </linearGradient>
            </defs>

            <CartesianGrid
              stroke="rgba(255,255,255,0.06)"
              vertical={false}
              strokeDasharray="3 3"
            />

            <XAxis
              dataKey="recorded_at"
              tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 12 }}
              tickFormatter={(value) => formatXAxis(value, range)}
              axisLine={false}
              tickLine={false}
              minTickGap={28}
            />

            <YAxis
              tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 12 }}
              tickFormatter={(value) => `$${Number(value).toFixed(0)}`}
              axisLine={false}
              tickLine={false}
              domain={yDomain as [number, number]}
              width={56}
            />

            <Tooltip
              formatter={(value: any) => {
                if (value === undefined || value === null) return "$0.00"; // Or any fallback string
                return formatMoney(Number(value));
              }}
              labelFormatter={(value) => formatTooltipLabel(String(value), range)}
              contentStyle={{
                background: "rgba(12,16,30,0.94)",
                border: "1px solid rgba(255,255,255,0.08)",
                borderRadius: 16,
                color: "#fff",
                boxShadow: "0 10px 30px rgba(0,0,0,0.28)",
              }}
              cursor={{
                stroke: "rgba(168,85,247,0.35)",
                strokeWidth: 1,
              }}
            />

            <Area
              type="monotone"
              dataKey="equity"
              stroke="#c084fc"
              strokeWidth={2.5}
              fill="url(#equityFill)"
              dot={false}
              activeDot={{
                r: 4,
                stroke: "#e9d5ff",
                strokeWidth: 2,
                fill: "#a855f7",
              }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}