import { useEffect, useMemo, useState } from "react";
import type {
  ConfigurationBootstrapResponse,
  ConfigurationSettings,
  SymbolUniverseItem,
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

const DEFAULT_GROUP = "independent";

function normalizeUniverseItem(item: Partial<SymbolUniverseItem> & { symbol: string }): SymbolUniverseItem {
  return {
    symbol: normalizeSymbol(item.symbol),
    enabled: item.enabled ?? true,
    priority: item.priority ?? 1,
    correlation_group: item.correlation_group || DEFAULT_GROUP,
  };
}

function universeSymbols(items: SymbolUniverseItem[]) {
  return items.filter((item) => item.enabled).map((item) => item.symbol);
}

function universeEqual(a?: SymbolUniverseItem[] | null, b?: SymbolUniverseItem[] | null) {
  return JSON.stringify(a ?? []) === JSON.stringify(b ?? []);
}

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

  const hasUnsavedChanges = useMemo(() => {
    if (!originalSettings || !settings) return false;
    return (
      !settingsEqual(originalSettings, settings) ||
      !universeEqual(originalSettings.symbol_universe, settings.symbol_universe)
    );
  }, [originalSettings, settings]);

  async function load(showLoading = false, showRefreshing = false) {
    try {
      if (showLoading) setLoading(true);
      if (showRefreshing) setRefreshing(true);

      const payload = await fetchConfigurationBootstrap();
      const normalizedSettings = {
        ...payload.settings,
        symbol_universe:
          payload.settings.symbol_universe?.length > 0
            ? payload.settings.symbol_universe.map(normalizeUniverseItem)
            : payload.settings.enabled_symbols.map((symbol) =>
                normalizeUniverseItem({ symbol, correlation_group: DEFAULT_GROUP })
              ),
      };

      setBootstrap({ ...payload, settings: normalizedSettings });
      setOriginalSettings(normalizedSettings);
      setSettings(normalizedSettings);
      setValidationMap(
        Object.fromEntries(
          normalizedSettings.symbol_universe.map((item) => [
            item.symbol,
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

    if (settings.symbol_universe.some((item) => item.symbol === normalized)) {
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
      const validation = await validateConfigurationSymbol(normalized);

      const nextUniverse = [
        ...settings.symbol_universe,
        normalizeUniverseItem({
          symbol: normalized,
          correlation_group: validation.default_correlation_group || DEFAULT_GROUP,
        }),
      ];

      setSettings({
        ...settings,
        symbol_universe: nextUniverse,
        enabled_symbols: universeSymbols(nextUniverse),
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

    const nextUniverse = settings.symbol_universe.filter((item) => item.symbol !== symbol);

    setSettings({
      ...settings,
      symbol_universe: nextUniverse,
      enabled_symbols: universeSymbols(nextUniverse),
    });
  }

  function handleUpdateCorrelationGroup(symbol: string, correlationGroup: string) {
    if (!settings) return;

    const nextUniverse = settings.symbol_universe.map((item) =>
      item.symbol === symbol
        ? {
            ...item,
            correlation_group: correlationGroup,
          }
        : item
    );

    setSettings({
      ...settings,
      symbol_universe: nextUniverse,
      enabled_symbols: universeSymbols(nextUniverse),
    });
  }

  function handleReset() {
    if (!originalSettings) return;
    setSettings(originalSettings);
    setValidationMap(
      Object.fromEntries(
        originalSettings.symbol_universe.map((item) => [
          item.symbol,
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

      if (!universeEqual(settings.symbol_universe, originalSettings.symbol_universe)) {
        const result = await saveConfigurationSymbolUniverse(settings.symbol_universe);

        const savedUniverse = result.symbols ?? settings.symbol_universe;
        const savedSymbols = result.enabled_symbols ?? universeSymbols(savedUniverse);

        const updated = {
          ...settings,
          symbol_universe: savedUniverse,
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

      <SymbolUniverseManager
        symbols={settings.symbol_universe}
        symbolInput={symbolInput}
        validationMap={validationMap}
        onInputChange={setSymbolInput}
        onAddSymbol={handleAddSymbol}
        onRemoveSymbol={handleRemoveSymbol}
        onUpdateCorrelationGroup={handleUpdateCorrelationGroup}
      />

      <div className="grid gap-6 xl:grid-cols-2">
        <GuardrailsPanel 
          settings={{
            maxRiskPct: settings.max_risk_pct,
            maxLeverage: settings.max_leverage,
            minNotionalPct: settings.min_notional_pct_of_max_deployable,
            limitFeePct: settings.limit_fee_pct,
            marketFeePct: settings.market_fee_pct,
            marketSlippagePct: settings.market_slippage_pct,
          }} 
        />
        <GlassCard>
          <SectionTitle
            title="Configuration Sources"
            subtitle="Every setting remains tied to its runtime owner to avoid drift"
          />
          <div className="mt-4 space-y-2 text-sm text-white/55">
            {Object.entries(bootstrap.sources).map(([key, value]) => (
              <div key={key} className="flex items-center justify-between gap-3 rounded-2xl bg-white/[0.04] px-4 py-3">
                <span>{key}</span>
                <span className="text-white/35">{String(value)}</span>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
