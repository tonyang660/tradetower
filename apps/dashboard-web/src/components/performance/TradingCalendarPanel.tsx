import ChartCard from "./ChartCard";
import type { CalendarDayItem, MonthlySummary } from "../../types/performance";
import { money, metricNumber, monthLabel } from "../../lib/performance";

type CalendarCell = {
  date: Date;
  isoDate: string;
  dayNumber: number;
  isCurrentMonth: boolean;
  isFuture: boolean;
  isToday: boolean;
  pnl: number;
  trades: number;
  winRate: number;
  hasData: boolean;
};

function toUtcIsoDate(date: Date) {
  const year = date.getUTCFullYear();
  const month = `${date.getUTCMonth() + 1}`.padStart(2, "0");
  const day = `${date.getUTCDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function utcDate(year: number, monthIndex: number, day: number) {
  return new Date(Date.UTC(year, monthIndex, day));
}

function monthFromSummaryOrNow(monthlySummary?: MonthlySummary) {
  const month = monthlySummary?.month;
  if (month && /^\d{4}-\d{2}$/.test(month)) {
    const [year, monthNumber] = month.split("-").map(Number);
    return {
      year,
      monthIndex: monthNumber - 1,
      monthKey: month,
    };
  }

  const now = new Date();
  return {
    year: now.getUTCFullYear(),
    monthIndex: now.getUTCMonth(),
    monthKey: `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`,
  };
}

function buildMonthCellsUtc(days: CalendarDayItem[], monthlySummary?: MonthlySummary): CalendarCell[] {
  const now = new Date();
  const { year: currentYear, monthIndex: currentMonth } = monthFromSummaryOrNow(monthlySummary);

  const firstDay = utcDate(currentYear, currentMonth, 1);
  const lastDay = utcDate(currentYear, currentMonth + 1, 0);

  const todayIso = toUtcIsoDate(now);
  const dayMap = new Map(days.map((d) => [d.date, d]));

  const cells: CalendarCell[] = [];

  const jsDay = firstDay.getUTCDay();
  const mondayFirstOffset = jsDay === 0 ? 6 : jsDay - 1;

  for (let i = 0; i < mondayFirstOffset; i++) {
    const blankDate = utcDate(currentYear, currentMonth, 1 - (mondayFirstOffset - i));
    cells.push({
      date: blankDate,
      isoDate: toUtcIsoDate(blankDate),
      dayNumber: blankDate.getUTCDate(),
      isCurrentMonth: false,
      isFuture: false,
      isToday: false,
      pnl: 0,
      trades: 0,
      winRate: 0,
      hasData: false,
    });
  }

  for (let day = 1; day <= lastDay.getUTCDate(); day++) {
    const cellDate = utcDate(currentYear, currentMonth, day);
    const isoDate = toUtcIsoDate(cellDate);
    const found = dayMap.get(isoDate);

    const isFuture = isoDate > todayIso;
    const isToday = isoDate === todayIso;

    cells.push({
      date: cellDate,
      isoDate,
      dayNumber: day,
      isCurrentMonth: true,
      isFuture,
      isToday,
      pnl: found?.pnl ?? 0,
      trades: found?.trades ?? 0,
      winRate: found?.win_rate ?? 0,
      hasData: !!found,
    });
  }

  while (cells.length % 7 !== 0) {
    const nextIndex = cells.length - (mondayFirstOffset + lastDay.getUTCDate()) + 1;
    const trailingDate = utcDate(currentYear, currentMonth + 1, nextIndex);
    cells.push({
      date: trailingDate,
      isoDate: toUtcIsoDate(trailingDate),
      dayNumber: trailingDate.getUTCDate(),
      isCurrentMonth: false,
      isFuture: true,
      isToday: false,
      pnl: 0,
      trades: 0,
      winRate: 0,
      hasData: false,
    });
  }

  return cells;
}

function cellTone(cell: CalendarCell) {
  if (!cell.isCurrentMonth) {
    return "border-white/5 bg-white/[0.025] text-white/16";
  }

  if (cell.isFuture) {
    return "border-white/10 bg-white/[0.07] text-white/78";
  }

  if (cell.pnl > 0) {
    return "border-emerald-400/15 bg-emerald-500/10 text-white";
  }

  if (cell.pnl < 0) {
    return "border-rose-400/15 bg-rose-500/10 text-white";
  }

  return "border-white/8 bg-white/5 text-white/70";
}

function todayRing(cell: CalendarCell) {
  return cell.isToday
    ? "ring-1 ring-violet-300/60 shadow-[0_0_0_1px_rgba(196,181,253,0.18),0_0_20px_rgba(168,85,247,0.18)]"
    : "";
}

const weekdayHeaders = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function TradingCalendarPanel({
  days,
  monthlySummary,
}: {
  days: CalendarDayItem[];
  monthlySummary: MonthlySummary;
}) {
  const cells = buildMonthCellsUtc(days, monthlySummary);
  const { monthKey } = monthFromSummaryOrNow(monthlySummary);
  const headerMonth = monthLabel(monthKey);

  return (
    <ChartCard
      title="Trading Calendar"
      subtitle="Day-by-day realized performance grouped by UTC close date"
      right={`${headerMonth} · UTC`}
    >
      <div className="grid gap-4 xl:grid-cols-[1.6fr_0.8fr]">
        <div>
          <div className="mb-3 grid grid-cols-7 gap-2">
            {weekdayHeaders.map((day) => (
              <div
                key={day}
                className="px-2 text-center text-[11px] uppercase tracking-[0.16em] text-white/35"
              >
                {day}
              </div>
            ))}
          </div>

          <div className="grid grid-cols-7 gap-2">
            {cells.map((cell) => (
              <div
                key={cell.isoDate}
                className={`min-h-[88px] rounded-[18px] border p-2.5 transition ${cellTone(cell)} ${todayRing(cell)}`}
              >
                <div className="flex items-start justify-between">
                  <div
                    className={`text-sm font-medium ${
                      !cell.isToday && !cell.isFuture
                        ? "text-white/30"
                        : "text-white"
                    }`}
                  >
                    {cell.dayNumber}
                  </div>

                  {cell.isToday ? (
                    <div className="rounded-full border border-violet-300/18 bg-violet-500/10 px-1.5 py-0.5 text-[10px] font-medium text-violet-200">
                      Today UTC
                    </div>
                  ) : null}
                </div>

                {cell.isCurrentMonth ? (
                  <div className="mt-3 space-y-1">
                    {!cell.isFuture ? (
                      <>
                        <div
                          className={`text-xs font-medium ${
                            cell.pnl > 0
                              ? "text-emerald-300"
                              : cell.pnl < 0
                              ? "text-rose-300"
                              : "text-white/65"
                          }`}
                        >
                          {money(cell.pnl)}
                        </div>
                        <div className="text-[11px] text-white/42">
                          {cell.trades} {cell.trades === 1 ? "trade" : "trades"}
                        </div>
                      </>
                    ) : (
                      <div className="pt-2 text-[11px] text-white/28">—</div>
                    )}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-3">
          <div className="rounded-[22px] border border-white/8 bg-white/5 p-4">
            <div className="text-sm text-white/40">Monthly PnL</div>
            <div className="mt-1 text-lg font-semibold text-white">
              {monthlySummary ? money(monthlySummary.pnl) : "$0.00"}
            </div>
            <div className="mt-1 text-sm text-white/50">
              {monthlySummary ? `${metricNumber(monthlySummary.pnl_pct, 2)}%` : "0.00%"}
            </div>
          </div>

          <div className="rounded-[22px] border border-white/8 bg-white/5 p-4 text-sm text-white/65">
            <div className="flex justify-between"><span>Winning days</span><span className="text-white">{monthlySummary?.winning_days ?? 0}</span></div>
            <div className="mt-2 flex justify-between"><span>Losing days</span><span className="text-white">{monthlySummary?.losing_days ?? 0}</span></div>
            <div className="mt-2 flex justify-between"><span>Flat days</span><span className="text-white">{monthlySummary?.flat_days ?? 0}</span></div>
            <div className="mt-3 border-t border-white/8 pt-3 flex justify-between"><span>Best day</span><span className="text-emerald-300">{money(monthlySummary?.best_day)}</span></div>
            <div className="mt-2 flex justify-between"><span>Worst day</span><span className="text-rose-300">{money(monthlySummary?.worst_day)}</span></div>
            <div className="mt-3 border-t border-white/8 pt-3 text-xs leading-relaxed text-white/35">
              Days are bucketed by UTC close date, matching hourly/session analytics.
            </div>
          </div>
        </div>
      </div>
    </ChartCard>
  );
}
