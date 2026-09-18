import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import * as authApi from "../services/authApi";
import type { LoginContext } from "../services/authApi";
import { clearStoredToken, getStoredToken, setStoredToken } from "../services/tokenStorage";
import type { User } from "../types/auth";

interface AuthContextValue {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  login: (email: string, password: string, loginContext?: LoginContext) => Promise<void>;
  register: (email: string, password: string, fullName: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // On first load, try to resume a session from a stored token by calling
  // /me - the backend re-validates the token and re-checks is_active on
  // every call (DECISIONS.md D21), so a stale or now-invalid token is
  // discarded here rather than trusted blindly.
  useEffect(() => {
    const storedToken = getStoredToken();
    if (!storedToken) {
      setIsLoading(false);
      return;
    }

    authApi
      .getCurrentUser(storedToken)
      .then((currentUser) => {
        setUser(currentUser);
        setToken(storedToken);
      })
      .catch(() => {
        clearStoredToken();
      })
      .finally(() => setIsLoading(false));
  }, []);

  async function login(email: string, password: string, loginContext?: LoginContext) {
    const response = await authApi.login(email, password, loginContext);
    setStoredToken(response.access_token);
    setToken(response.access_token);
    setUser(response.user);
  }

  async function register(email: string, password: string, fullName: string) {
    await authApi.register(email, password, fullName);
    await login(email, password);
  }

  function logout() {
    if (token) {
      // Best-effort only: the MVP logout strategy is stateless (DECISIONS.md
      // D22), so this call can't actually invalidate anything server-side.
      // Discarding the local token below is what actually ends the session.
      authApi.logout(token).catch(() => undefined);
    }
    clearStoredToken();
    setToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, token, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
