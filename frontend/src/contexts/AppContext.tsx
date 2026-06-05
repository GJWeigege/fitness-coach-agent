import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type AppContextValue = {
  error: string;
  setError: (msg: string) => void;
  clearError: () => void;
};

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [error, setErrorState] = useState("");

  const setError = useCallback((msg: string) => setErrorState(msg), []);
  const clearError = useCallback(() => setErrorState(""), []);

  return (
    <AppContext.Provider value={{ error, setError, clearError }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}
