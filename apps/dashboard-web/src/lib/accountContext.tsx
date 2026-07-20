
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { createAccount, fetchAccounts, updateAccount } from "./api";

export type TradeTowerAccount = {
  account_id: number;
  account_name: string;
  account_type: "paper" | "live";
  execution_mode: "paper" | "shadow" | "live";
  enabled: boolean;
  exchange?: string | null;
  base_currency: string;
  starting_equity: number;
  current_equity: number;
};

const AccountContext = createContext<any>(null);
const STORAGE_KEY = "tradetower.selectedAccountId";

export function AccountProvider({ children }: { children: React.ReactNode }) {
  const [accounts, setAccounts] = useState<TradeTowerAccount[]>([]);
  const [selectedAccountId, setSelectedAccountIdState] = useState<number>(() => Number(window.localStorage.getItem(STORAGE_KEY) || "1"));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function reloadAccounts() {
    try {
      setLoading(true);
      const payload = await fetchAccounts();
      const nextAccounts = payload.accounts ?? [];
      setAccounts(nextAccounts);
      if (!nextAccounts.some((a: TradeTowerAccount) => a.account_id === selectedAccountId) && nextAccounts.length > 0) {
        const fallback = payload.default_selected_account_id ?? nextAccounts[0].account_id;
        setSelectedAccountIdState(fallback);
        window.localStorage.setItem(STORAGE_KEY, String(fallback));
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load accounts");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { reloadAccounts(); }, []);

  function setSelectedAccountId(accountId: number) {
    setSelectedAccountIdState(accountId);
    window.localStorage.setItem(STORAGE_KEY, String(accountId));
  }

  const selectedAccount = useMemo(() => accounts.find((a) => a.account_id === selectedAccountId) ?? accounts[0] ?? null, [accounts, selectedAccountId]);

  return (
    <AccountContext.Provider value={{
      accounts,
      selectedAccountId: selectedAccount?.account_id ?? selectedAccountId,
      selectedAccount,
      loading,
      error,
      reloadAccounts,
      setSelectedAccountId,
      createNewAccount: async (payload: Record<string, unknown>) => { await createAccount(payload); await reloadAccounts(); },
      updateExistingAccount: async (payload: Record<string, unknown>) => { await updateAccount(payload); await reloadAccounts(); },
    }}>
      {children}
    </AccountContext.Provider>
  );
}

export function useSelectedAccount() {
  const value = useContext(AccountContext);
  if (!value) throw new Error("useSelectedAccount must be used inside AccountProvider");
  return value;
}
