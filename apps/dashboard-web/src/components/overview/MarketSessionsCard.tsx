import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";

function formatSessionHours(openHour: number, closeHour: number) {
  const open = `${String(openHour).padStart(2, "0")}:00 UTC`;
  const close = `${String(closeHour).padStart(2, "0")}:00 UTC`;
  return `${open} - ${close}`;
}

function buildSegments(openHour: number, closeHour: number) {
  if (closeHour > openHour) {
    return [
      {
        left: `${(openHour / 24) * 100}%`,
        width: `${((closeHour - openHour) / 24) * 100}%`,
      },
    ];
  }

  // Crosses midnight, split into two visible segments
  return [
    {
      left: `${(openHour / 24) * 100}%`,
      width: `${((24 - openHour) / 24) * 100}%`,
    },
    {
      left: "0%",
      width: `${(closeHour / 24) * 100}%`,
    },
  ];
}

export default function MarketSessionsCard({
  now,
  activeSessions,
  nextSessionName,
  nextSessionCountdown,
  sessionRows,
}: {
  now: string;
  activeSessions: string[];
  nextSessionName: string | null;
  nextSessionCountdown: string;
  sessionRows: Array<{
    name: string;
    open_hour_utc: number;
    close_hour_utc: number;
    is_active: boolean;
  }>;
}) {
  const nowDate = new Date(now);
  const currentHour = nowDate.getUTCHours() + nowDate.getUTCMinutes() / 60 + nowDate.getUTCSeconds() / 3600;
  const currentLeft = `${(currentHour / 24) * 100}%`;

  return (
    <GlassCard className="h-full">
      <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <SectionTitle title="Market Sessions" subtitle="Global market overlap and timing" />

          <div className="max-w-[560px] text-[1.2rem] font-semibold leading-[1.05] tracking-tight text-white xl:text-[1.7rem]">
            {new Date(now).toLocaleString([], {
              year: "numeric",
              month: "numeric",
              day: "numeric",
              hour: "numeric",
              minute: "2-digit",
              second: "2-digit",
            })}
          </div>

          <div className="mt-3 text-sm text-white/50">
            Active: {activeSessions.length > 0 ? activeSessions.join(" + ") : "No major overlap"}
          </div>
        </div>

        <div className="w-full rounded-3xl border border-white/10 bg-white/6 px-5 py-4 text-sm xl:w-[320px]">
          <div className="text-white/50">Next session</div>
          <div className="mt-1 text-xl font-medium text-white">
            {nextSessionName ? `${nextSessionName} opens in ${nextSessionCountdown}` : "-"}
          </div>
        </div>
      </div>

      {sessionRows.length === 0 ? (
      <div className="mt-8 rounded-2xl border border-white/8 bg-white/5 p-4 text-sm text-white/45">
        Session timeline unavailable.
      </div>
      ) : (
        <div className="mt-8 space-y-4">
          ...
        </div>
      )}

      <div className="mt-8 space-y-4">
        {sessionRows.map((row) => {
          const segments = buildSegments(row.open_hour_utc, row.close_hour_utc);

          return (
            <div key={row.name}>
              <div className="mb-2 flex items-center justify-between text-sm">
                <div className="flex items-center gap-3">
                  <span className={`font-medium ${row.is_active ? "text-white" : "text-white/65"}`}>
                    {row.name}
                  </span>
                  <span className="text-xs text-white/35">
                    {formatSessionHours(row.open_hour_utc, row.close_hour_utc)}
                  </span>
                </div>

                <span className={row.is_active ? "text-emerald-200" : "text-white/35"}>
                  {row.is_active ? "Open" : "Closed"}
                </span>
              </div>

              <div className="relative h-4 overflow-hidden rounded-full bg-white/6">
                {segments.map((segment, idx) => (
                  <div
                    key={idx}
                    className={`absolute top-0 h-4 rounded-full ${
                      row.is_active
                        ? "bg-gradient-to-r from-purple-500/80 to-violet-300/80"
                        : "bg-white/12"
                    }`}
                    style={{
                      left: segment.left,
                      width: segment.width,
                    }}
                  />
                ))}

                <div
                  className="absolute top-[-4px] z-10 h-6 w-[2px] rounded-full bg-white/90 shadow-[0_0_10px_rgba(255,255,255,0.7)]"
                  style={{ left: currentLeft }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </GlassCard>
  );
}