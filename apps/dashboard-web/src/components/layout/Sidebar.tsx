import { Activity, BarChart3, Gauge, LayoutDashboard, Shield, SlidersHorizontal } from "lucide-react";
import { NavLink } from "react-router-dom";
import clsx from "clsx";

const items = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/live-cycle-monitor", label: "Live Cycle Monitor", icon: Activity },
  { to: "/positions-orders", label: "Positions & Orders", icon: Gauge },
  { to: "/performance", label: "Performance", icon: BarChart3 },
  { to: "/strategy-analytics", label: "Strategy Analytics", icon: SlidersHorizontal },
  { to: "/system-health", label: "System Health", icon: Shield },
];

export default function Sidebar() {
  return (
    <aside className="w-[280px] shrink-0 border-r border-white/10 bg-white/5 backdrop-blur-xl">
      <div className="flex h-full flex-col px-5 py-6">
        <div className="mb-8">
          <div className="text-xs uppercase tracking-[0.28em] text-white/40">Trading Platform</div>
          <div className="mt-2 text-2xl font-semibold tracking-tight text-white">Control Center</div>
          <div className="mt-2 text-sm text-white/50">Glassy dashboard with live strategy telemetry.</div>
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
                    "flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-medium transition-all duration-200",
                    isActive
                      ? "border border-white/15 bg-white/12 text-white shadow-glass"
                      : "text-white/60 hover:bg-white/8 hover:text-white"
                  )
                }
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        <div className="mt-auto rounded-3xl border border-white/10 bg-white/5 p-4 text-sm text-white/55">
          <div className="font-medium text-white/80">Paper Account</div>
          <div className="mt-1">Start with a clean shell, then expand each page carefully.</div>
        </div>
      </div>
    </aside>
  );
}
