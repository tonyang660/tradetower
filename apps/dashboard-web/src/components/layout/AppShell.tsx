import type { ReactNode } from "react";
import { useEffect, useState } from "react";
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
          <div className="mx-auto max-w-[1600px] px-6 py-6 lg:px-8">{children}</div>
        </main>
      </div>
    </div>
  );
}