import {
  Activity,
  BarChart3,
  Gauge,
  LayoutDashboard,
  Shield,
  SlidersHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import clsx from "clsx";

const items = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/live-cycle-monitor", label: "Live Cycle Monitor", icon: Activity },
  { to: "/positions-orders", label: "Positions & Orders", icon: Gauge },
  { to: "/performance", label: "Performance", icon: BarChart3 },
  { to: "/strategy-analytics", label: "Strategy Analytics", icon: SlidersHorizontal },
  { to: "/system-health", label: "System Health", icon: Shield },
  { to: "/configuration", label: "Configuration", icon: Settings},
];

export default function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <aside
      className={clsx(
        "shrink-0 border-r border-white/10 bg-white/5 backdrop-blur-xl transition-all duration-300 ease-out",
        collapsed ? "w-[88px]" : "w-[260px]"
      )}
    >
      <div className="flex h-full flex-col px-4 py-5">
        <div className={clsx("mb-6 flex items-start", collapsed ? "justify-center" : "justify-between")}>
          {!collapsed ? (
            <div>
              <div className="text-[11px] uppercase tracking-[0.28em] text-white/40">TradeTower</div>
              <div className="mt-2 text-2xl font-semibold tracking-tight text-white">Control Center</div>
              <div className="mt-2 text-sm text-white/50">
                Live strategy telemetry.
              </div>
            </div>
          ) : null}

          <button
            onClick={onToggle}
            className="rounded-2xl border border-white/10 bg-white/8 p-2 text-white/75 transition hover:bg-white/12 hover:text-white"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          </button>
        </div>

        <nav className="space-y-2">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  clsx(
                    "flex items-center rounded-2xl px-4 py-2.5 text-sm font-medium transition-all duration-200",
                    collapsed ? "justify-center" : "gap-3",
                    isActive
                      ? "border border-white/15 bg-white/12 text-white shadow-glass"
                      : "text-white/60 hover:bg-white/8 hover:text-white"
                  )
                }
                title={collapsed ? item.label : undefined}
              >
                <Icon size={18} />
                {!collapsed ? <span>{item.label}</span> : null}
              </NavLink>
            );
          })}
        </nav>

        {!collapsed ? (
          <div className="mt-auto rounded-3xl border border-white/10 bg-white/5 p-4 text-sm text-white/55">
            <div className="font-medium text-white/80">Paper Account</div>
            <div className="mt-1">Build each page carefully, then grow it into the full operator dashboard.</div>
          </div>
        ) : (
          <div className="mt-auto flex justify-center">
            <div
              className="h-10 w-10 rounded-2xl border border-white/10 bg-white/6"
              title="Paper account"
            />
          </div>
        )}
      </div>
    </aside>
  );
}