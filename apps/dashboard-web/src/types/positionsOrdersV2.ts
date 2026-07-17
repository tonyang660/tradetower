import type {
  ExecutedOrder,
  OpenPosition,
  RecentClosedPosition,
  WorkingOrder,
} from "./positionsOrders";

export type PositionsOrdersV2Error = {
  source?: string;
  path?: string;
  status_code?: number | null;
  error?: unknown;
};

export type PositionsOrdersV2ServiceBlock<T = unknown> = {
  ok: boolean;
  data: T | null;
  error: PositionsOrdersV2Error | null;
};

export type PositionLifecycleV2Summary = Record<string, any>;

export type PositionsOrdersV2Response = {
  ok: boolean;
  partial: boolean;
  positions_orders_v2_version: string;
  account_id: number;
  generated_at: string;
  open_positions: OpenPosition[];
  recent_closed_positions: RecentClosedPosition[];
  open_orders: WorkingOrder[];
  executed_orders: ExecutedOrder[];
  recent_position_lifecycles: PositionLifecycleV2Summary[];
  counts: {
    open_positions: number;
    recent_closed_positions: number;
    open_orders: number;
    executed_orders: number;
    recent_position_lifecycles: number;
  };
  raw?: Record<string, any>;
  services: {
    open_positions?: PositionsOrdersV2ServiceBlock;
    recent_positions?: PositionsOrdersV2ServiceBlock;
    open_orders?: PositionsOrdersV2ServiceBlock;
    executed_orders?: PositionsOrdersV2ServiceBlock;
    recent_position_lifecycles?: PositionsOrdersV2ServiceBlock;
    [key: string]: PositionsOrdersV2ServiceBlock | undefined;
  };
  errors: PositionsOrdersV2Error[];
};

export type PositionLifecycleV2Response = {
  ok: boolean;
  positions_orders_v2_version: string;
  account_id: number;
  position_id: number;
  generated_at: string;
  lifecycle?: Record<string, any>;
  error?: PositionsOrdersV2Error;
};
