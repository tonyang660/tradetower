import type {
  ExposureRibbonSegment,
  OpenPosition,
  PositionsAnalytics,
  PositionsOrdersViewModel,
  RecentClosedPosition,
  WorkingOrder,
} from "../types/positionsOrders";

function safeNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function normalizeSide(value: unknown): "long" | "short" {
  return String(value).toLowerCase() === "short" ? "short" : "long";
}

function normalizeOrderRole(role: unknown): string {
  const value = String(role ?? "").toLowerCase().trim();
  return value || "entry";
}

function orderRoleRank(role: string): number {
  switch (role) {
    case "stop_loss":
      return 0;
    case "tp1":
      return 1;
    case "tp2":
      return 2;
    case "tp3":
      return 3;
    case "entry":
      return 4;
    default:
      return 5;
  }
}

function deriveMarginUsed(position: OpenPosition): number {
  const explicit = safeNumber(position.margin_used, NaN);
  if (Number.isFinite(explicit)) return explicit;

  const notional = deriveNotional(position);
  const leverage = safeNumber(position.leverage, NaN);

  if (Number.isFinite(notional) && Number.isFinite(leverage) && leverage > 0) {
    return notional / leverage;
  }

  return 0;
}

function deriveNotional(position: OpenPosition): number {
  const explicit = safeNumber(position.notional, NaN);
  if (Number.isFinite(explicit)) return explicit;

  const entry = safeNumber(position.entry_price, NaN);
  const size = safeNumber(
    position.remaining_size ?? position.original_size ?? position.size,
    NaN
  );

  if (Number.isFinite(entry) && Number.isFinite(size)) {
    return entry * size;
  }

  return 0;
}

function enrichOpenPosition(
  position: OpenPosition
): OpenPosition & { pnl_pct_on_margin: number } {
  const notional = deriveNotional(position);
  const marginUsed = deriveMarginUsed(position);
  const unrealizedPnl = safeNumber(position.unrealized_pnl, 0);
  const feesPaid = safeNumber(position.fees_paid, 0);
  const pnlPctOnMargin = marginUsed > 0 ? (unrealizedPnl / marginUsed) * 100 : 0;

  return {
    ...position,
    side: normalizeSide(position.side),
    notional,
    margin_used: marginUsed,
    unrealized_pnl: unrealizedPnl,
    fees_paid: feesPaid,
    pnl_pct_on_margin: pnlPctOnMargin,
  };
}

function normalizeWorkingOrder(order: WorkingOrder): WorkingOrder {
  const normalizedRole = normalizeOrderRole(order.role);

  return {
    ...order,
    side: normalizeSide(order.side),
    role: normalizedRole,
    entry_price:
      typeof order.entry_price === "number" && Number.isFinite(order.entry_price)
        ? order.entry_price
        : null,
    requested_size:
      typeof order.requested_size === "number" && Number.isFinite(order.requested_size)
        ? order.requested_size
        : null,
    stop_loss:
      typeof order.stop_loss === "number" && Number.isFinite(order.stop_loss)
        ? order.stop_loss
        : null,
    tp1:
      typeof order.tp1 === "number" && Number.isFinite(order.tp1)
        ? order.tp1
        : null,
    tp2:
      typeof order.tp2 === "number" && Number.isFinite(order.tp2)
        ? order.tp2
        : null,
    tp3:
      typeof order.tp3 === "number" && Number.isFinite(order.tp3)
        ? order.tp3
        : null,
    linked_position_id:
      typeof order.linked_position_id === "number" && Number.isFinite(order.linked_position_id)
        ? order.linked_position_id
        : null,
    submitted_at: order.submitted_at ?? null,
    updated_at: order.updated_at ?? null,
  };
}

export function buildPositionsOrdersViewModel(
  openPositions: OpenPosition[],
  recentClosed: RecentClosedPosition[],
  workingOrders: WorkingOrder[]
): PositionsOrdersViewModel {
  const enriched = openPositions.map(enrichOpenPosition);

  const normalizedOrders = workingOrders
    .map(normalizeWorkingOrder)
    .sort((a, b) => {
      const positionDelta =
        (a.linked_position_id ?? Number.MAX_SAFE_INTEGER) -
        (b.linked_position_id ?? Number.MAX_SAFE_INTEGER);

      if (positionDelta !== 0) return positionDelta;

      const roleDelta = orderRoleRank(String(a.role)) - orderRoleRank(String(b.role));
      if (roleDelta !== 0) return roleDelta;

      return a.symbol.localeCompare(b.symbol);
    });

  const totalNotional = enriched.reduce((acc, p) => acc + safeNumber(p.notional, 0), 0);
  const totalMarginUsed = enriched.reduce((acc, p) => acc + safeNumber(p.margin_used, 0), 0);
  const totalOpenPnl = enriched.reduce((acc, p) => acc + safeNumber(p.unrealized_pnl, 0), 0);
  const totalOpenPnlPctOnMargin =
    totalMarginUsed > 0 ? (totalOpenPnl / totalMarginUsed) * 100 : 0;

  const longPositions = enriched.filter((p) => p.side === "long");
  const shortPositions = enriched.filter((p) => p.side === "short");

  const longExposureNotional = longPositions.reduce(
    (acc, p) => acc + safeNumber(p.notional, 0),
    0
  );
  const shortExposureNotional = shortPositions.reduce(
    (acc, p) => acc + safeNumber(p.notional, 0),
    0
  );

  const longExposurePct = totalNotional > 0 ? (longExposureNotional / totalNotional) * 100 : 0;
  const shortExposurePct =
    totalNotional > 0 ? (shortExposureNotional / totalNotional) * 100 : 0;

  const sortedByPnl = [...enriched].sort(
    (a, b) => safeNumber(b.unrealized_pnl, 0) - safeNumber(a.unrealized_pnl, 0)
  );

  const biggestWinner = sortedByPnl.find((p) => safeNumber(p.unrealized_pnl, 0) > 0) ?? null;
  const biggestLoser =
    [...sortedByPnl].reverse().find((p) => safeNumber(p.unrealized_pnl, 0) < 0) ?? null;

  const analytics: PositionsAnalytics = {
    open_positions: enriched.length,
    total_notional: totalNotional,
    total_margin_used: totalMarginUsed,
    total_open_pnl: totalOpenPnl,
    total_open_pnl_pct_on_margin: totalOpenPnlPctOnMargin,
    long_exposure_notional: longExposureNotional,
    short_exposure_notional: shortExposureNotional,
    long_exposure_pct: longExposurePct,
    short_exposure_pct: shortExposurePct,
    biggest_winner_symbol: biggestWinner?.symbol ?? null,
    biggest_winner_pnl: biggestWinner ? safeNumber(biggestWinner.unrealized_pnl, 0) : null,
    biggest_loser_symbol: biggestLoser?.symbol ?? null,
    biggest_loser_pnl: biggestLoser ? safeNumber(biggestLoser.unrealized_pnl, 0) : null,
  };

  const exposureSegments: ExposureRibbonSegment[] = enriched
    .map((p) => ({
      symbol: p.symbol,
      side: normalizeSide(p.side),
      value: safeNumber(p.notional, 0),
      pnl: safeNumber(p.unrealized_pnl, 0),
    }))
    .sort((a, b) => b.value - a.value);

  return {
    openPositions: enriched,
    recentClosed,
    workingOrders: normalizedOrders,
    analytics,
    exposureSegments,
  };
}