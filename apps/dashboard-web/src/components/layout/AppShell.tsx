import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import Sidebar from "./Sidebar";

export default function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem("dashboard.sidebar.collapsed");
    if (saved === "true") setCollapsed(true);
  }, []);

  useEffect(() => {
    window.localStorage.setItem("dashboard.sidebar.collapsed", String(collapsed));
  }, [collapsed]);

  return (
    <div className="min-h-screen bg-transparent text-white">
      <div className="flex min-h-screen">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />

        <main className="flex-1 transition-all duration-300">
          <div className="mx-auto max-w-[1600px] px-6 py-5 lg:px-8">
            <header className="mb-6 flex items-center justify-between rounded-[28px] border border-white/10 bg-white/5 px-5 py-4 shadow-glass backdrop-blur-xl">
              <div>
                <div className="text-[11px] uppercase tracking-[0.28em] text-white/40">
                  TradeTower
                </div>
                <div className="mt-1 text-2xl font-semibold tracking-tight text-white">
                  Home Lab Control Center
                </div>
                <div className="mt-1 text-sm text-white/45">
                  Live operations, analytics, and decision telemetry
                </div>
              </div>

              <div className="flex items-center gap-3">
                <div className="rounded-2xl border border-emerald-400/15 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
                  <span className="inline-flex items-center gap-2">
                    <ShieldCheck size={15} />
                    Auth reserved
                  </span>
                </div>

                <div className="rounded-2xl border border-white/10 bg-white/6 px-4 py-2 text-sm text-white/55">
                  Future logout / user menu
                </div>
              </div>
            </header>

            {children}
          </div>
        </main>
      </div>
    </div>
  );
}