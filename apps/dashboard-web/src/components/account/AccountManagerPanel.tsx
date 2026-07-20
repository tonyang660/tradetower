
import { useState } from "react";
import { Plus, RefreshCcw } from "lucide-react";
import { useSelectedAccount } from "../../lib/accountContext";

export default function AccountManagerPanel() {
  const { accounts, selectedAccountId, selectedAccount, error, reloadAccounts, setSelectedAccountId, createNewAccount, updateExistingAccount } = useSelectedAccount();
  const [creating, setCreating] = useState(false);
  const [accountName, setAccountName] = useState("");
  const [accountType, setAccountType] = useState<"paper" | "live">("paper");
  const [executionMode, setExecutionMode] = useState<"paper" | "shadow" | "live">("paper");
  const [startingEquity, setStartingEquity] = useState("2000");
  const [busy, setBusy] = useState(false);

  async function submitCreate() {
    setBusy(true);
    try {
      await createNewAccount({
        account_name: accountName,
        account_type: accountType,
        execution_mode: accountType === "paper" ? "paper" : executionMode,
        starting_equity: Number(startingEquity),
        enabled: true,
        exchange: accountType === "paper" ? "paper" : "bitget",
        base_currency: "USDT",
      });
      setCreating(false);
      setAccountName("");
    } finally { setBusy(false); }
  }

  async function toggleEnabled() {
    if (!selectedAccount) return;
    setBusy(true);
    try { await updateExistingAccount({ account_id: selectedAccount.account_id, enabled: !selectedAccount.enabled }); }
    finally { setBusy(false); }
  }

  return (
    <div className="min-w-[360px] rounded-3xl border border-white/10 bg-black/20 p-3 text-sm shadow-glass backdrop-blur-xl">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-[0.22em] text-white/35">Account Manager</div>
          <div className="text-white/85">{selectedAccount ? selectedAccount.account_name : "No account"}</div>
        </div>
        <button onClick={reloadAccounts} className="rounded-xl border border-white/10 bg-white/6 p-2 text-white/60 hover:text-white"><RefreshCcw size={14} /></button>
      </div>
      {error ? <div className="mb-2 text-xs text-rose-200">{error}</div> : null}
      <div className="flex gap-2">
        <select value={selectedAccountId} onChange={(e) => setSelectedAccountId(Number(e.target.value))} className="min-w-0 flex-1 rounded-2xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none">
          {accounts.map((a: any) => <option key={a.account_id} value={a.account_id}>#{a.account_id} {a.account_name}</option>)}
        </select>
        <button onClick={() => setCreating((v) => !v)} className="rounded-2xl border border-cyan-300/15 bg-cyan-500/10 px-3 py-2 text-cyan-100"><Plus size={15} /></button>
      </div>
      {selectedAccount ? (
        <div className="mt-2 flex flex-wrap gap-2 text-xs">
          <span className="rounded-full border border-white/10 bg-white/6 px-2 py-1 text-white/65">{selectedAccount.account_type}</span>
          <span className="rounded-full border border-white/10 bg-white/6 px-2 py-1 text-white/65">{selectedAccount.execution_mode}</span>
          <button onClick={toggleEnabled} disabled={busy} className={`rounded-full border px-2 py-1 ${selectedAccount.enabled ? "border-emerald-300/20 bg-emerald-500/10 text-emerald-200" : "border-rose-300/20 bg-rose-500/10 text-rose-200"}`}>{selectedAccount.enabled ? "Enabled" : "Disabled"}</button>
        </div>
      ) : null}
      {creating ? (
        <div className="mt-3 grid gap-2 rounded-2xl border border-white/10 bg-white/5 p-3">
          <input value={accountName} onChange={(e) => setAccountName(e.target.value)} placeholder="Account name" className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none" />
          <div className="grid grid-cols-2 gap-2">
            <select value={accountType} onChange={(e) => { const next = e.target.value as "paper" | "live"; setAccountType(next); setExecutionMode(next === "paper" ? "paper" : "shadow"); }} className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none"><option value="paper">paper</option><option value="live">live</option></select>
            <select value={accountType === "paper" ? "paper" : executionMode} disabled={accountType === "paper"} onChange={(e) => setExecutionMode(e.target.value as "shadow" | "live")} className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none disabled:opacity-50"><option value="paper">paper</option><option value="shadow">shadow</option><option value="live">live</option></select>
          </div>
          <input value={startingEquity} onChange={(e) => setStartingEquity(e.target.value)} placeholder="Starting equity" type="number" min="1" className="rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-white outline-none" />
          <button onClick={submitCreate} disabled={busy || !accountName.trim()} className="rounded-xl border border-emerald-300/20 bg-emerald-500/10 px-3 py-2 text-emerald-100 disabled:opacity-50">Create account</button>
        </div>
      ) : null}
    </div>
  );
}
