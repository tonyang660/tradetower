import { Routes, Route } from "react-router-dom";
import AppShell from "./components/layout/AppShell";
import OverviewPage from "./pages/OverviewPage";
import LiveCycleMonitorPage from "./pages/LiveCycleMonitorPage";
import PositionsOrdersPage from "./pages/PositionsOrdersPage";
import PerformancePage from "./pages/PerformancePage";
import StrategyAnalyticsPage from "./pages/StrategyAnalyticsPage";
import BacktestPage from "./pages/BacktestPage";
import SystemHealthPage from "./pages/SystemHealthPage";
import ConfigurationPage from "./pages/ConfigurationPage";
import { AccountProvider } from "./lib/accountContext";

export default function App() {
  return (
    <AccountProvider>
      <AppShell>
        <Routes>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/live-cycle-monitor" element={<LiveCycleMonitorPage />} />
        <Route path="/positions-orders" element={<PositionsOrdersPage />} />
        <Route path="/performance" element={<PerformancePage />} />
        <Route path="/strategy-analytics" element={<StrategyAnalyticsPage />} />
        <Route path="/backtest" element={<BacktestPage />} />
        <Route path="/system-health" element={<SystemHealthPage />} />
        <Route path="/configuration" element={<ConfigurationPage />} />
        </Routes>
      </AppShell>
    </AccountProvider>
  );
}