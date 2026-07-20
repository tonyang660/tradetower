import GlassCard from "../ui/GlassCard";
import SectionTitle from "../ui/SectionTitle";

type PositionLifecycleLike = Record<string, any>;

type PositionEventLike = Record<string, any> & {
  _position_id: any;
  _symbol: any;
  position_event_id?: string | number | null;
  execution_id?: string | number | null;
  event_timestamp?: string | null;
  created_at?: string | null;
  timestamp?: string | null;
  recorded_at?: string | null;
  time?: string | null;
  event_type?: string | null;
  type?: string | null;
  action?: string | null;
  label?: string | null;
  source?: string | null;
  kind?: string | null;
  price?: string | number | null;
  trigger_price?: string | number | null;
  fill_price?: string | number | null;
  details_json?: Record<string, any> | null;
  details?: Record<string, any> | null;
  raw_details?: Record<string, any> | null;
  payload?: Record<string, any> | null;
};

type Props = {
  lifecycles: PositionLifecycleLike[];
};

function normalizeTimelineItem(item: Record<string, any>): Record<string, any> {
  const payload = item.payload && typeof item.payload === "object" ? item.payload : {};

  return {
    ...payload,
    ...item,
    event_timestamp:
      payload.event_timestamp ??
      item.event_timestamp ??
      item.time ??
      payload.created_at ??
      item.created_at ??
      null,
    event_type:
      payload.event_type ??
      item.event_type ??
      item.label ??
      item.action ??
      item.kind ??
      "EVENT",
    details_json:
      payload.details_json ??
      payload.details ??
      item.details_json ??
      item.details ??
      item.raw_details ??
      null,
    price:
      payload.price ??
      item.price ??
      payload.trigger_price ??
      item.trigger_price ??
      payload.fill_price ??
      item.fill_price ??
      null,
  };
}

function getEvents(item: PositionLifecycleLike): Record<string, any>[] {
  const direct = item.events ?? item.items;
  if (Array.isArray(direct)) return direct;

  if (Array.isArray(item.position_events) && item.position_events.length > 0) {
    return item.position_events;
  }

  if (Array.isArray(item.timeline) && item.timeline.length > 0) {
    return item.timeline.map(normalizeTimelineItem);
  }

  if (Array.isArray(item.executions) && item.executions.length > 0) {
    return item.executions.map((execution: Record<string, any>) => ({
      ...execution,
      event_type: execution.execution_type,
      event_timestamp: execution.executed_at,
      price: execution.fill_price,
      details_json: execution.details,
    }));
  }

  if (Array.isArray(item.position_management_events) && item.position_management_events.length > 0) {
    return item.position_management_events.map((event: Record<string, any>) => ({
      ...event,
      event_type: event.event_type,
      event_timestamp: event.event_time,
      details_json: event.payload,
    }));
  }

  const lifecycle = item.lifecycle;
  if (lifecycle && Array.isArray(lifecycle.events)) return lifecycle.events;
  if (lifecycle && Array.isArray(lifecycle.items)) return lifecycle.items;
  if (lifecycle && Array.isArray(lifecycle.position_events)) return lifecycle.position_events;
  if (lifecycle && Array.isArray(lifecycle.timeline)) return lifecycle.timeline.map(normalizeTimelineItem);

  return [];
}

function eventTime(event: PositionEventLike) {
  return (
    event.event_timestamp ??
    event.created_at ??
    event.timestamp ??
    event.recorded_at ??
    event.time ??
    null
  );
}

function eventType(event: PositionEventLike) {
  return event.event_type ?? event.type ?? event.action ?? event.label ?? "EVENT";
}

function eventPrice(event: PositionEventLike) {
  const value = event.price ?? event.trigger_price ?? event.fill_price;
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function compactDetails(event: PositionEventLike) {
  const details = event.details_json ?? event.details ?? event.raw_details ?? event.payload;
  if (!details || typeof details !== "object") return null;

  const keys = [
    "close_reason",
    "old_price",
    "new_price",
    "role",
    "order_role",
    "realized_pnl",
    "fee_paid",
    "reason",
    "reason_code",
    "action",
    "module",
  ];

  const parts = keys
    .filter((key) => details[key] !== undefined && details[key] !== null)
    .map((key) => `${key}: ${details[key]}`);

  return parts.length ? parts.join(" · ") : null;
}

export default function PositionEventsPanel({ lifecycles }: Props) {
  const flattened: PositionEventLike[] = lifecycles.flatMap((item) => {
    const events = getEvents(item);
    const positionId =
      item.position_id ??
      item.lifecycle?.position_id ??
      item.position?.position_id ??
      "—";
    const symbol =
      item.symbol ??
      item.lifecycle?.symbol ??
      item.position?.symbol ??
      "—";

    return events.map((event): PositionEventLike => ({
      ...event,
      _position_id: event.position_id ?? event.payload?.position_id ?? positionId,
      _symbol:
        event.symbol ??
        event.payload?.symbol ??
        event.details_json?.symbol ??
        event.details?.symbol ??
        symbol,
    }));
  });

  const events = flattened
    .sort((a, b) => String(eventTime(b) ?? "").localeCompare(String(eventTime(a) ?? "")))
    .slice(0, 80);

  return (
    <GlassCard className="h-full">
      <SectionTitle
        title="Position Events"
        subtitle="Lifecycle audit trail for fills, stop reprices, and protective-order changes"
      />

      {events.length === 0 ? (
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/45">
          No position events available yet.
        </div>
      ) : (
        <div className="max-h-[560px] space-y-2 overflow-y-auto pr-2">
          {events.map((event, idx) => {
            const price = eventPrice(event);
            const details = compactDetails(event);
            const key = `${event._position_id}-${event.position_event_id ?? event.execution_id ?? event.event_timestamp ?? idx}`;

            return (
              <div
                key={key}
                className="rounded-2xl border border-white/10 bg-white/6 p-3"
              >
                <div className="flex flex-col gap-2 2xl:flex-row 2xl:items-start 2xl:justify-between">
                  <div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-sm font-semibold text-white">{event._symbol}</span>
                      <span className="rounded-full border border-white/10 bg-white/8 px-2 py-0.5 text-[10px] text-white/60">
                        Pos {event._position_id}
                      </span>
                      {event.source ? (
                        <span className="rounded-full border border-white/10 bg-white/8 px-2 py-0.5 text-[10px] text-white/45">
                          {event.source}
                        </span>
                      ) : null}
                      <span className="rounded-full border border-cyan-300/15 bg-cyan-400/10 px-2 py-0.5 text-[10px] text-cyan-100">
                        {eventType(event)}
                      </span>
                    </div>

                    {details ? (
                      <div className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-white/55">
                        {details}
                      </div>
                    ) : null}
                  </div>

                  <div className="shrink-0 text-left text-xs 2xl:text-right">
                    {price !== null ? (
                      <div className="text-white/85">Price {price.toFixed(6)}</div>
                    ) : null}
                    <div className="text-white/40">
                      {eventTime(event) ? new Date(String(eventTime(event))).toLocaleString() : "No timestamp"}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </GlassCard>
  );
}
