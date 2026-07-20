import { useEffect, useState } from "react";
import { AlertTriangle, Plus, RefreshCcw, Save, ShieldCheck } from "lucide-react";
import { fetchGuardianAccountPolicy, updateGuardianAccountPolicy } from "../../lib/api";
import { useSelectedAccount, type TradeTowerAccount } from "../../lib/accountContext";

type GuardianPolicy = {
  account_id: number;
  account_name: string;
  account_type: "paper" | "live";
  enabled: boolean;
  is_active: boolean;
  execution_mode: "paper" | "shadow" | "live";
  trading_enabled: boolean;
  manual_halt: boolean;
  daily_kill_switch: boolean;
  weekly_kill_switch: boolean;
  max_concurrent_positions: number;
  daily_loss_limit_pct: number;
  weekly_loss_limit_pct: number;
  max_account_exposure_pct: number;
  read_only_mode: boolean;
  maintenance_only_mode: boolean;
  policy_updated_at?: string | null;
  policy_updated_by?: string | null;
};

function validExecutionModes(accountType: "paper" | "live") {
  return accountType === "paper"
    ? (["paper"] as const)
    : (["shadow", "live"] as const);
}

function yesNo(value: boolean) {
  return value ? "On" : "Off";
}

export default function AccountManagerPanel() {
  const {
    accounts,
    selectedAccountId,
    selectedAccount,
    error,
    reloadAccounts,
    setSelectedAccountId,
    createNewAccount,
    updateExistingAccount,
  } = useSelectedAccount();

  const [creating, setCreating] = useState(false);
  const [accountName, setAccountName] = useState("");
  const [accountType, setAccountType] = useState<"paper" | "live">("paper");
  const [executionMode, setExecutionMode] = useState<"paper" | "shadow" | "live">("paper");
  const [startingEquity, setStartingEquity] = useState("2000");
  const [selectedStartingEquity, setSelectedStartingEquity] = useState("");
  const [busy, setBusy] = useState(false);

  const [policyDraft, setPolicyDraft] = useState<GuardianPolicy | null>(null);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [policyOpen, setPolicyOpen] = useState(false);

  useEffect(() => {
    if (!selectedAccount) return;
    setSelectedStartingEquity(String(selectedAccount.starting_equity ?? 0));
  }, [selectedAccount?.account_id, selectedAccount?.starting_equity]);

  async function reloadPolicy(accountId = selectedAccountId) {
    try {
      const payload = await fetchGuardianAccountPolicy(accountId);
      const nextPolicy = payload.policy ?? null;
      setPolicyDraft(nextPolicy ? { ...nextPolicy } : null);
      setPolicyError(null);
    } catch (err) {
      setPolicyError(err instanceof Error ? err.message : "Failed to load guardian policy");
      setPolicyDraft(null);
    }
  }

  useEffect(() => {
    if (!selectedAccountId) return;
    reloadPolicy(selectedAccountId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAccountId]);

  function handleCreateAccountType(next: "paper" | "live") {
    setAccountType(next);
    setExecutionMode(next === "paper" ? "paper" : "shadow");
  }

  async function submitCreate() {
    const safeMode =
      accountType === "paper"
        ? "paper"
        : executionMode === "live"
        ? "live"
        : "shadow";

    setBusy(true);
    try {
      await createNewAccount({
        account_name: accountName.trim(),
        account_type: accountType,
        execution_mode: safeMode,
        starting_equity: Number(startingEquity),
        enabled: true,
        exchange: accountType === "paper" ? "paper" : "bitget",
        base_currency: "USDT",
      });

      setCreating(false);
      setAccountName("");
      setStartingEquity("2000");
      handleCreateAccountType("paper");
      await reloadAccounts();
    } finally {
      setBusy(false);
    }
  }

  async function toggleEnabled() {
    if (!selectedAccount) return;
    setBusy(true);
    try {
      await updateGuardianAccountPolicy(selectedAccount.account_id, {
        enabled: !(policyDraft?.enabled ?? selectedAccount.enabled),
      });
      await reloadAccounts();
      await reloadPolicy(selectedAccount.account_id);
    } finally {
      setBusy(false);
    }
  }

  async function toggleLiveMode() {
    if (!selectedAccount || selectedAccount.account_type !== "live") return;
    setBusy(true);
    try {
      const nextMode = selectedAccount.execution_mode === "shadow" ? "live" : "shadow";
      await updateGuardianAccountPolicy(selectedAccount.account_id, {
        execution_mode: nextMode,
      });
      await reloadAccounts();
      await reloadPolicy(selectedAccount.account_id);
    } finally {
      setBusy(false);
    }
  }

  async function saveStartingEquity() {
    if (!selectedAccount) return;

    const value = Number(selectedStartingEquity);
    if (!Number.isFinite(value) || value <= 0) return;

    setBusy(true);
    try {
      await updateExistingAccount({
        account_id: selectedAccount.account_id,
        starting_equity: value,
      });
    } finally {
      setBusy(false);
    }
  }

  async function savePolicy() {
    if (!selectedAccount || !policyDraft) return;
    setBusy(true);
    try {
      await updateGuardianAccountPolicy(selectedAccount.account_id, {
        enabled: policyDraft.enabled,
        execution_mode: policyDraft.execution_mode,
        trading_enabled: policyDraft.trading_enabled,
        manual_halt: policyDraft.manual_halt,
        daily_kill_switch: policyDraft.daily_kill_switch,
        weekly_kill_switch: policyDraft.weekly_kill_switch,
        max_concurrent_positions: Number(policyDraft.max_concurrent_positions),
        daily_loss_limit_pct: Number(policyDraft.daily_loss_limit_pct),
        weekly_loss_limit_pct: Number(policyDraft.weekly_loss_limit_pct),
        max_account_exposure_pct: Number(policyDraft.max_account_exposure_pct),
        read_only_mode: policyDraft.read_only_mode,
        maintenance_only_mode: policyDraft.maintenance_only_mode,
        policy_updated_by: "dashboard",
      });
      await reloadAccounts();
      await reloadPolicy(selectedAccount.account_id);
    } finally {
      setBusy(false);
    }
  }

  function updatePolicyDraft<K extends keyof GuardianPolicy>(key: K, value: GuardianPolicy[K]) {
    setPolicyDraft((draft) => (draft ? { ...draft, [key]: value } : draft));
  }

  const createModes = validExecutionModes(accountType);
  const selectedEnabled = policyDraft?.enabled ?? selectedAccount?.enabled ?? false;
  const selectedMode = policyDraft?.execution_mode ?? selectedAccount?.execution_mode ?? "paper";
  const selectedAccountType = policyDraft?.account_type ?? selectedAccount?.account_type ?? "paper";
  const policyModes = validExecutionModes(selectedAccountType);

  return (
    <div className="w-full rounded-3xl border border-white/10 bg-black/20 p-3 text-sm shadow-glass backdrop-blur-xl">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-[0.22em] text-white/35">Account Manager</div>
          <div className="text-white/85">{selectedAccount ? selectedAccount.account_name : "No account"}</div>
        </div>

        <button
          onClick={async () => {
            await reloadAccounts();
            await reloadPolicy();
          }}
          className="rounded-xl border border-white/10 bg-white/6 p-2 text-white/60 hover:text-white"
          title="Refresh accounts"
        >
          <RefreshCcw size={14} />
        </button>
      </div>

      {error ? <div className="mb-2 text-xs text-rose-200">{error}</div> : null}
      {policyError ? <div className="mb-2 text-xs text-rose-200">{policyError}</div> : null}

      <div className="flex gap-2">
        <select
          value={selectedAccountId}
          onChange={(event) => setSelectedAccountId(Number(event.target.value))}
          className="min-w-0 flex-1 rounded-2xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none"
        >
          {accounts.map((account: TradeTowerAccount) => (
            <option key={account.account_id} value={account.account_id}>
              #{account.account_id} {account.account_name}
            </option>
          ))}
        </select>

        <button
          onClick={() => setCreating((value) => !value)}
          className="rounded-2xl border border-cyan-300/15 bg-cyan-500/10 px-3 py-2 text-cyan-100"
          title="Create account"
        >
          <Plus size={15} />
        </button>
      </div>

      {selectedAccount ? (
        <div className="mt-2 grid gap-2">
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="rounded-full border border-white/10 bg-white/6 px-2 py-1 text-white/65">
              {selectedAccount.account_type}
            </span>
            <span className="rounded-full border border-white/10 bg-white/6 px-2 py-1 text-white/65">
              {selectedMode}
            </span>
            <button
              onClick={toggleEnabled}
              disabled={busy}
              className={`rounded-full border px-2 py-1 ${
                selectedEnabled
                  ? "border-emerald-300/20 bg-emerald-500/10 text-emerald-200"
                  : "border-rose-300/20 bg-rose-500/10 text-rose-200"
              }`}
            >
              {selectedEnabled ? "Enabled" : "Disabled"}
            </button>

            {policyDraft?.read_only_mode ? (
              <span className="rounded-full border border-sky-300/20 bg-sky-500/10 px-2 py-1 text-sky-100">
                Read-only
              </span>
            ) : null}

            {policyDraft?.maintenance_only_mode ? (
              <span className="rounded-full border border-amber-300/20 bg-amber-500/10 px-2 py-1 text-amber-100">
                Maintenance-only
              </span>
            ) : null}

            {selectedAccount.account_type === "live" ? (
              <button
                onClick={toggleLiveMode}
                disabled={busy}
                className="rounded-full border border-amber-300/20 bg-amber-500/10 px-2 py-1 text-amber-100"
              >
                Toggle {selectedMode === "shadow" ? "Live" : "Shadow"}
              </button>
            ) : null}

            <button
              onClick={() => setPolicyOpen((value) => !value)}
              className="rounded-full border border-cyan-300/20 bg-cyan-500/10 px-2 py-1 text-cyan-100"
            >
              <ShieldCheck size={12} className="mr-1 inline" />
              Guardian Policy
            </button>
          </div>

          {selectedAccount.account_type === "live" ? (
            <div className="flex items-center gap-2 rounded-2xl border border-white/10 bg-white/5 p-2">
              <div className="min-w-0 flex-1">
                <div className="text-[10px] uppercase tracking-[0.18em] text-white/35">Starting Equity</div>
                <input
                  value={selectedStartingEquity}
                  onChange={(event) => setSelectedStartingEquity(event.target.value)}
                  type="number"
                  min="1"
                  className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none"
                />
              </div>
              <button
                onClick={saveStartingEquity}
                disabled={busy}
                className="mt-5 rounded-xl border border-cyan-300/20 bg-cyan-500/10 p-2 text-cyan-100 disabled:opacity-50"
                title="Save starting equity"
              >
                <Save size={15} />
              </button>
            </div>
          ) : null}

          {policyOpen && policyDraft ? (
            <div className="grid gap-3 rounded-2xl border border-white/10 bg-white/5 p-3">
              <div className="flex items-start gap-2 rounded-xl border border-amber-300/15 bg-amber-500/10 p-2 text-xs text-amber-100/80">
                <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                <div>
                  Disabled blocks new cycles/entries. Maintenance-only can be used while the account stays enabled, so exits
                  and risk-reduction logic continue without allowing new exposure.
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs">
                <label className="rounded-xl border border-white/10 bg-black/20 p-2">
                  <div className="text-white/40">Enabled</div>
                  <button
                    onClick={() => updatePolicyDraft("enabled", !policyDraft.enabled)}
                    className={`mt-1 rounded-full border px-3 py-1 ${
                      policyDraft.enabled ? "border-emerald-300/20 bg-emerald-500/10 text-emerald-200" : "border-rose-300/20 bg-rose-500/10 text-rose-200"
                    }`}
                  >
                    {yesNo(policyDraft.enabled)}
                  </button>
                </label>

                <label className="rounded-xl border border-white/10 bg-black/20 p-2">
                  <div className="text-white/40">Execution mode</div>
                  <select
                    value={policyDraft.execution_mode}
                    onChange={(event) => updatePolicyDraft("execution_mode", event.target.value as GuardianPolicy["execution_mode"])}
                    className="mt-1 w-full rounded-xl border border-white/10 bg-black/40 px-2 py-1 text-white outline-none"
                  >
                    {policyModes.map((mode) => (
                      <option key={mode} value={mode}>
                        {mode}
                      </option>
                    ))}
                  </select>
                </label>

                {[
                  ["trading_enabled", "Trading enabled"],
                  ["manual_halt", "Manual halt"],
                  ["read_only_mode", "Read-only"],
                  ["maintenance_only_mode", "Maintenance-only"],
                  ["daily_kill_switch", "Daily kill switch"],
                  ["weekly_kill_switch", "Weekly kill switch"],
                ].map(([key, label]) => (
                  <label key={key} className="rounded-xl border border-white/10 bg-black/20 p-2">
                    <div className="text-white/40">{label}</div>
                    <button
                      onClick={() =>
                        updatePolicyDraft(
                          key as keyof GuardianPolicy,
                          !policyDraft[key as keyof GuardianPolicy] as never,
                        )
                      }
                      className={`mt-1 rounded-full border px-3 py-1 ${
                        policyDraft[key as keyof GuardianPolicy]
                          ? "border-amber-300/20 bg-amber-500/10 text-amber-100"
                          : "border-white/10 bg-white/6 text-white/65"
                      }`}
                    >
                      {yesNo(Boolean(policyDraft[key as keyof GuardianPolicy]))}
                    </button>
                  </label>
                ))}
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs">
                <label className="rounded-xl border border-white/10 bg-black/20 p-2">
                  <div className="text-white/40">Max positions</div>
                  <input
                    type="number"
                    min="0"
                    value={policyDraft.max_concurrent_positions}
                    onChange={(event) => updatePolicyDraft("max_concurrent_positions", Number(event.target.value))}
                    className="mt-1 w-full rounded-xl border border-white/10 bg-black/40 px-2 py-1 text-white outline-none"
                  />
                </label>

                <label className="rounded-xl border border-white/10 bg-black/20 p-2">
                  <div className="text-white/40">Max exposure %</div>
                  <input
                    type="number"
                    min="0"
                    value={policyDraft.max_account_exposure_pct}
                    onChange={(event) => updatePolicyDraft("max_account_exposure_pct", Number(event.target.value))}
                    className="mt-1 w-full rounded-xl border border-white/10 bg-black/40 px-2 py-1 text-white outline-none"
                  />
                </label>

                <label className="rounded-xl border border-white/10 bg-black/20 p-2">
                  <div className="text-white/40">Daily loss %</div>
                  <input
                    type="number"
                    min="0"
                    value={policyDraft.daily_loss_limit_pct}
                    onChange={(event) => updatePolicyDraft("daily_loss_limit_pct", Number(event.target.value))}
                    className="mt-1 w-full rounded-xl border border-white/10 bg-black/40 px-2 py-1 text-white outline-none"
                  />
                </label>

                <label className="rounded-xl border border-white/10 bg-black/20 p-2">
                  <div className="text-white/40">Weekly loss %</div>
                  <input
                    type="number"
                    min="0"
                    value={policyDraft.weekly_loss_limit_pct}
                    onChange={(event) => updatePolicyDraft("weekly_loss_limit_pct", Number(event.target.value))}
                    className="mt-1 w-full rounded-xl border border-white/10 bg-black/40 px-2 py-1 text-white outline-none"
                  />
                </label>
              </div>

              <button
                onClick={savePolicy}
                disabled={busy}
                className="rounded-xl border border-emerald-300/20 bg-emerald-500/10 px-3 py-2 text-emerald-100 disabled:opacity-50"
              >
                Save Guardian Policy
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {creating ? (
        <div className="mt-3 grid gap-2 rounded-2xl border border-white/10 bg-white/5 p-3">
          <input
            value={accountName}
            onChange={(event) => setAccountName(event.target.value)}
            placeholder="Account name"
            className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none"
          />

          <div className="grid grid-cols-2 gap-2">
            <select
              value={accountType}
              onChange={(event) => handleCreateAccountType(event.target.value as "paper" | "live")}
              className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none"
            >
              <option value="paper">paper</option>
              <option value="live">live</option>
            </select>

            <select
              value={executionMode}
              onChange={(event) => setExecutionMode(event.target.value as "paper" | "shadow" | "live")}
              className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none"
            >
              {createModes.map((mode) => (
                <option key={mode} value={mode}>
                  {mode}
                </option>
              ))}
            </select>
          </div>

          {accountType === "live" ? (
            <div className="rounded-xl border border-amber-300/15 bg-amber-500/10 px-3 py-2 text-xs text-amber-100/80">
              Live accounts can only start in shadow or live execution mode. Starting equity stays editable for exchange
              reconciliation.
            </div>
          ) : null}

          <input
            value={startingEquity}
            onChange={(event) => setStartingEquity(event.target.value)}
            placeholder="Starting equity"
            type="number"
            min="1"
            className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none"
          />

          <button
            onClick={submitCreate}
            disabled={busy || !accountName.trim() || Number(startingEquity) <= 0}
            className="rounded-xl border border-emerald-300/20 bg-emerald-500/10 px-3 py-2 text-emerald-100 disabled:opacity-50"
          >
            Create account
          </button>
        </div>
      ) : null}
    </div>
  );
}
