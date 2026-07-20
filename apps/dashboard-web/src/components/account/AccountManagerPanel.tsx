import { useEffect, useState } from "react";
import { Plus, RefreshCcw, Save } from "lucide-react";
import { useSelectedAccount } from "../../lib/accountContext";

function validExecutionModes(accountType: "paper" | "live") {
  return accountType === "paper"
    ? (["paper"] as const)
    : (["shadow", "live"] as const);
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

  useEffect(() => {
    if (!selectedAccount) return;
    setSelectedStartingEquity(String(selectedAccount.starting_equity ?? 0));
  }, [selectedAccount?.account_id, selectedAccount?.starting_equity]);

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
      setAccountType("paper");
      setExecutionMode("paper");
    } finally {
      setBusy(false);
    }
  }

  async function toggleEnabled() {
    if (!selectedAccount) return;
    setBusy(true);
    try {
      await updateExistingAccount({
        account_id: selectedAccount.account_id,
        enabled: !selectedAccount.enabled,
      });
    } finally {
      setBusy(false);
    }
  }

  async function toggleLiveMode() {
    if (!selectedAccount || selectedAccount.account_type !== "live") return;
    setBusy(true);
    try {
      await updateExistingAccount({
        account_id: selectedAccount.account_id,
        execution_mode: selectedAccount.execution_mode === "shadow" ? "live" : "shadow",
      });
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

  const createModes = validExecutionModes(accountType);

  return (
    <div className="min-w-[380px] rounded-3xl border border-white/10 bg-black/20 p-3 text-sm shadow-glass backdrop-blur-xl">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-[0.22em] text-white/35">Account Manager</div>
          <div className="text-white/85">{selectedAccount ? selectedAccount.account_name : "No account"}</div>
        </div>

        <button
          onClick={reloadAccounts}
          className="rounded-xl border border-white/10 bg-white/6 p-2 text-white/60 hover:text-white"
          title="Refresh accounts"
        >
          <RefreshCcw size={14} />
        </button>
      </div>

      {error ? <div className="mb-2 text-xs text-rose-200">{error}</div> : null}

      <div className="flex gap-2">
        <select
          value={selectedAccountId}
          onChange={(event) => setSelectedAccountId(Number(event.target.value))}
          className="min-w-0 flex-1 rounded-2xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none"
        >
          {accounts.map((account: { account_id: number; account_name: string }) => (
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
              {selectedAccount.execution_mode}
            </span>
            <button
              onClick={toggleEnabled}
              disabled={busy}
              className={`rounded-full border px-2 py-1 ${
                selectedAccount.enabled
                  ? "border-emerald-300/20 bg-emerald-500/10 text-emerald-200"
                  : "border-rose-300/20 bg-rose-500/10 text-rose-200"
              }`}
            >
              {selectedAccount.enabled ? "Enabled" : "Disabled"}
            </button>

            {selectedAccount.account_type === "live" ? (
              <button
                onClick={toggleLiveMode}
                disabled={busy}
                className="rounded-full border border-amber-300/20 bg-amber-500/10 px-2 py-1 text-amber-100"
              >
                Toggle {selectedAccount.execution_mode === "shadow" ? "Live" : "Shadow"}
              </button>
            ) : null}
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
              Live accounts can only start in shadow or live execution mode. Starting equity stays editable later for
              exchange reconciliation.
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
