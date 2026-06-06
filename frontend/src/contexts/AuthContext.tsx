import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchMe, fetchPermissionMatrix, login, register } from "../api/auth";
import type { UserProfile } from "../types";

type AuthContextValue = {
  token: string;
  me: UserProfile | null;
  permissionMatrix: Record<string, string[]>;
  permissions: Set<string>;
  authError: string;
  setAuthError: (msg: string) => void;
  loginUser: (username: string, password: string) => Promise<void>;
  registerUser: (username: string, password: string) => Promise<void>;
  logout: () => void;
  loading: boolean;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(() => localStorage.getItem("token") || "");
  const [me, setMe] = useState<UserProfile | null>(null);
  const [permissionMatrix, setPermissionMatrix] = useState<Record<string, string[]>>({});
  const [authError, setAuthError] = useState("");
  const [loading, setLoading] = useState(Boolean(token));

  const permissions = useMemo(() => new Set(me?.permissions || []), [me]);

  useEffect(() => {
    if (!token) {
      return;
    }
    void (async () => {
      setLoading(true);
      try {
        const profile = await fetchMe(token);
        setMe(profile);
        setPermissionMatrix(await fetchPermissionMatrix(token));
      } catch (err) {
        setAuthError((err as Error).message);
        localStorage.removeItem("token");
        setToken("");
        setMe(null);
        setPermissionMatrix({});
      } finally {
        setLoading(false);
      }
    })();
  }, [token]);

  async function persistAuth(result: { access_token: string; user: UserProfile }) {
    localStorage.setItem("token", result.access_token);
    setToken(result.access_token);
    setMe(result.user);
    setPermissionMatrix(await fetchPermissionMatrix(result.access_token));
    setAuthError("");
  }

  async function loginUser(username: string, password: string) {
    await persistAuth(await login({ username, password }));
  }

  async function registerUser(username: string, password: string) {
    await persistAuth(await register({ username, password }));
  }

  function logout() {
    localStorage.removeItem("token");
    setToken("");
    setMe(null);
    setPermissionMatrix({});
    setAuthError("");
  }

  return (
    <AuthContext.Provider
      value={{
        token,
        me,
        permissionMatrix,
        permissions,
        authError,
        setAuthError,
        loginUser,
        registerUser,
        logout,
        loading,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function usePermissions() {
  const { permissions } = useAuth();
  return {
    canSendChat: permissions.has("chat:send"),
    canManageOwnSession: permissions.has("session:manage:own"),
    canManageAllSession: permissions.has("session:manage:all"),
    canViewKnowledge: permissions.has("knowledge:read"),
    canManageKnowledge: permissions.has("knowledge:write"),
    canReindexKnowledge: permissions.has("knowledge:reindex"),
    canManageUsers: permissions.has("user:manage"),
    canViewObservability: permissions.has("observability:read"),
    canRunBenchmark: permissions.has("benchmark:run"),
    canReadBenchmark: permissions.has("benchmark:read"),
    canWriteFeedback: permissions.has("feedback:write"),
  };
}
