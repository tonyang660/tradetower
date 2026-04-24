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

function enrichOpenPosition(position: OpenPosition): OpenPosition & { pnl_pct_on_margin: number } {
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
  return {
    ...order,
    side: normalizeSide(order.side),
    role: order.role ?? "entry",
    entry_price: order.entry_price ?? null,
    requested_size: order.requested_size ?? null,
    stop_loss: order.stop_loss ?? null,
    tp1: order.tp1 ?? null,
    tp2: order.tp2 ?? null,
    tp3: order.tp3 ?? null,
    linked_position_id: order.linked_position_id ?? null,
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

  const normalizedOrders = workingOrders.map(normalizeWorkingOrder);

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
  const shortExposurePct = totalNotional > 0 ? (shortExposureNotional / totalNotional) * 100 : 0;

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