import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, onUnauthorized } from "../api";
import type { User } from "../types";
import { LoginScreen } from "../pages/LoginScreen";

interface AuthContextValue {
  user: User;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth() called outside AuthGate");
  return ctx;
}

/**
 * Gates the whole app behind a login/first-run-setup screen. Renders
 * children (the real app) only once a valid session exists, and registers
 * the api layer's global 401 handler so a session expiring mid-use bounces
 * back here too, not just on initial load.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(undefined); // undefined = still checking
  const [needsSetup, setNeedsSetup] = useState(false);

  const check = useCallback(() => {
    api.authStatus()
      .then((s) => {
        setUser(s.user);
        setNeedsSetup(s.needs_setup);
      })
      .catch(() => {
        setUser(null);
        setNeedsSetup(false);
      });
  }, []);

  useEffect(() => {
    check();
    onUnauthorized(() => setUser(null));
  }, [check]);

  async function logout() {
    await api.logout().catch(() => {});
    setUser(null);
  }

  if (user === undefined) {
    return <div className="flex min-h-screen items-center justify-center text-muted">Loading…</div>;
  }
  if (!user) {
    return <LoginScreen needsSetup={needsSetup} onAuthenticated={check} />;
  }
  return <AuthContext.Provider value={{ user, logout }}>{children}</AuthContext.Provider>;
}
