import { Routes, Route } from "react-router-dom";
import AppShell from "./components/layout/AppShell";
import OverviewPage from "./pages/OverviewPage";
import LiveCycleMonitorPage from "./pages/LiveCycleMonitorPage";
import PositionsOrdersPage from "./pages/PositionsOrdersPage";

function PlaceholderPage({ title }: { title: string }) {
  return (
    <div className="rounded-[28px] border border-white/10 bg-white/6 p-6 shadow-glass backdrop-blur-xl">
      <div className="text-2xl font-semibold tracking-tight text-white">{title}</div>
      <div className="mt-2 text-white/50">This page is currently under construction.</div>
    </div>
  );
}

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/live-cycle-monitor" element={<LiveCycleMonitorPage />} />
        <Route path="/positions-orders" element={<PositionsOrdersPage />} />
        <Route path="/performance" element={<PlaceholderPage title="Performance" />} />
        <Route path="/strategy-analytics" element={<PlaceholderPage title="Strategy Analytics" />} />
        <Route path="/system-health" element={<PlaceholderPage title="System Health" />} />
      </Routes>
    </AppShell>
  );
}