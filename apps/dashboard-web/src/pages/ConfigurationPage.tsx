import { useEffect, useMemo, useState } from "react";
import type {
  ConfigurationBootstrapResponse,
  ConfigurationSettings,
} from "../types/configuration";
import {
  fetchConfigurationBootstrap,
  saveConfigurationSymbolUniverse,
  setConfigurationAutoLoop,
  validateConfigurationSymbol,
} from "../lib/api";
import { normalizeSymbol, settingsEqual } from "../lib/configuration";
import ConfigurationHero from "../components/configuration/ConfigurationHero";
import ConfigurationControls from "../components/configuration/ConfigurationControls";
import RuntimeControlsPanel from "../components/configuration/RuntimeControlsPanel";
import StrictnessPanel from "../components/configuration/StrictnessPanel";
import SymbolUniverseManager from "../components/configuration/SymbolUniverseManager";
import GuardrailsPanel from "../components/configuration/GuardrailsPanel";
import GlassCard from "../components/ui/GlassCard";
import SectionTitle from "../components/ui/SectionTitle";

type ValidationMap = Record<
  string,
  {
    state: "valid" | "invalid" | "pending";
    message?: string;
  }
>;

export default function ConfigurationPage() {
  const [bootstrap, setBootstrap] = useState<ConfigurationBootstrapResponse | null>(null);
  const [originalSettings, setOriginalSettings] = useState<ConfigurationSettings | null>(null);
  const [settings, setSettings] = useState<ConfigurationSettings | null>(null);
  const [validationMap, setValidationMap] = useState<ValidationMap>({});
  const [symbolInput, setSymbolInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasUnsavedChanges = useMemo(
    () => !settingsEqual(originalSettings, settings),
    [originalSettings, settings]
  );

  async function load(showLoading = false, showRefreshing = false) {
    try {
      if (showLoading) setLoading(true);
      if (showRefreshing) setRefreshing(true);

      const payload = await fetchConfigurationBootstrap();
      setBootstrap(payload);
      setOriginalSettings(payload.settings);
      setSettings(payload.settings);
      setValidationMap(
        Object.fromEntries(
          payload.settings.enabled_symbols.map((symbol) => [
            symbol,
            { state: "valid" as const, message: "Validated" },
          ])
        )
      );
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      if (showLoading) setLoading(false);
      if (showRefreshing) setRefreshing(false);
    }
  }

  useEffect(() => {
    load(true, false);
  }, []);

  async function handleToggleAutoLoop(enabled: boolean) {
    if (!settings) return;

    try {
      setSaving(true);
      await setConfigurationAutoLoop(enabled);

      const updated = {
        ...settings,
        auto_loop_enabled: enabled,
      };

      setSettings(updated);
      setOriginalSettings(updated);
      setBootstrap((prev) =>
        prev
          ? {
              ...prev,
              settings: updated,
            }
          : prev
      );
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update auto loop");
    } finally {
      setSaving(false);
    }
  }

  async function handleAddSymbol() {
    if (!settings) return;

    const normalized = normalizeSymbol(symbolInput);
    if (!normalized) return;

    if (settings.enabled_symbols.includes(normalized)) {
      setValidationMap((prev) => ({
        ...prev,
        [normalized]: { state: "invalid", message: "Duplicate symbol" },
      }));
      setSymbolInput("");
      return;
    }

    setValidationMap((prev) => ({
      ...prev,
      [normalized]: { state: "pending", message: "Validating..." },
    }));

    try {
      await validateConfigurationSymbol(normalized);

      setSettings({
        ...settings,
        enabled_symbols: [...settings.enabled_symbols, normalized],
      });

      setValidationMap((prev) => ({
        ...prev,
        [normalized]: { state: "valid", message: "Validated successfully" },
      }));
      setSymbolInput("");
      setError(null);
    } catch (err) {
      setValidationMap((prev) => ({
        ...prev,
        [normalized]: {
          state: "invalid",
          message: err instanceof Error ? err.message : "Validation failed",
        },
      }));
    }
  }

  function handleRemoveSymbol(symbol: string) {
    if (!settings) return;

    setSettings({
      ...settings,
      enabled_symbols: settings.enabled_symbols.filter((s) => s !== symbol),
    });
  }

  function handleReset() {
    if (!originalSettings) return;
    setSettings(originalSettings);
    setValidationMap(
      Object.fromEntries(
        originalSettings.enabled_symbols.map((symbol) => [
          symbol,
          { state: "valid" as const, message: "Validated" },
        ])
      )
    );
    setSymbolInput("");
  }

  async function handleSave() {
    if (!settings || !originalSettings) return;

    try {
      setSaving(true);

      if (settings.enabled_symbols.join(",") !== originalSettings.enabled_symbols.join(",")) {
        const result = await saveConfigurationSymbolUniverse(settings.enabled_symbols);

        const savedSymbols = result.enabled_symbols ?? settings.enabled_symbols;

        const updated = {
          ...settings,
          enabled_symbols: savedSymbols,
        };

        setSettings(updated);
        setOriginalSettings(updated);
        setBootstrap((prev) =>
          prev
            ? {
                ...prev,
                settings: updated,
              }
            : prev
        );
      }

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save configuration");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="text-white/70">Loading configuration...</div>;
  }

  if (error && !bootstrap) {
    return (
      <div className="rounded-3xl border border-red-400/20 bg-red-500/10 p-6 text-red-200">
        Failed to load configuration. {error}
      </div>
    );
  }

  if (!bootstrap || !settings) {
    return null;
  }

  return (
    <div className="space-y-6">
      {error ? (
        <div className="rounded-3xl border border-amber-400/20 bg-amber-500/10 p-4 text-amber-200">
          {error}
        </div>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[1.45fr_0.75fr]">
        <ConfigurationHero
          environment={bootstrap.environment}
          generatedAt={bootstrap.generated_at}
          hasUnsavedChanges={hasUnsavedChanges}
        />
        <ConfigurationControls
          refreshing={refreshing}
          saving={saving}
          hasUnsavedChanges={hasUnsavedChanges}
          onRefresh={() => load(false, true)}
          onReset={handleReset}
          onSave={handleSave}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <RuntimeControlsPanel
          autoLoopEnabled={settings.auto_loop_enabled}
          loopIntervalSeconds={settings.loop_interval_seconds}
          mtmEnabled={settings.mtm_auto_refresh_enabled}
          mtmIntervalSeconds={settings.mtm_auto_refresh_interval_seconds}
          onToggleAutoLoop={handleToggleAutoLoop}
        />
        <StrictnessPanel strictScoreThreshold={settings.strict_score_threshold} />
      </div>

      <GlassCard>
        <SectionTitle
          title="Order Cycle"
          subtitle="Dedicated pending-entry retry loop runtime"
        />

        <div className="mt-4 grid gap-4 md:grid-cols-4">
          <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
            <div className="text-xs text-white/40">Main Cycle</div>
            <div className="mt-1 text-lg font-semibold text-white">
              {settings.loop_interval_seconds}s
            </div>
          </div>

          <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
            <div className="text-xs text-white/40">Order Cycle</div>
            <div className="mt-1 text-lg font-semibold text-white">
              {settings.pending_entry_loop_interval_seconds}s
            </div>
          </div>

          <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
            <div className="text-xs text-white/40">Max Attempts</div>
            <div className="mt-1 text-lg font-semibold text-white">
              {settings.pending_entry_max_attempts}
            </div>
          </div>

          <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
            <div className="text-xs text-white/40">Pending Entries</div>
            <div className="mt-1 text-lg font-semibold text-white">
              {settings.pending_entries_count}
            </div>
          </div>
        </div>

        <div className="mt-4 text-sm text-white/45">
          Pending entries are repriced through the scheduler-owned order cycle.
          These values are runtime-controlled and currently read-only in the UI.
        </div>
      </GlassCard>      

      <SymbolUniverseManager
        symbols={settings.enabled_symbols}
        symbolInput={symbolInput}
        validationMap={validationMap}
        onInputChange={setSymbolInput}
        onAddSymbol={handleAddSymbol}
        onRemoveSymbol={handleRemoveSymbol}
      />

      <GuardrailsPanel
        maxRiskPct={settings.max_risk_pct}
        maxLeverage={settings.max_leverage}
        minNotionalPct={settings.min_notional_pct_of_max_deployable}
        limitFeePct={settings.limit_fee_pct}
        marketFeePct={settings.market_fee_pct}
        marketSlippagePct={settings.market_slippage_pct}
      />
    </div>
  );
}