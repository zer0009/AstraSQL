import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Spinner } from "../components/ui";
import {
  changePassword as changePasswordApi,
  getMe,
  login as loginApi,
  logout as logoutApi,
  setAuthRedirectHandler,
} from "../services/api";
import type { AuthUser } from "../types/api";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<AuthUser>;
  refresh: () => Promise<AuthUser | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async (): Promise<AuthUser | null> => {
    try {
      const me = await getMe();
      setUser(me);
      return me;
    } catch {
      setUser(null);
      return null;
    }
  }, []);

  useEffect(() => {
    void refresh().finally(() => setLoading(false));
  }, [refresh]);

  useEffect(() => {
    setAuthRedirectHandler((to) => {
      if (to === "/login") {
        setUser(null);
      }
      navigate(to);
    });
    return () => setAuthRedirectHandler(null);
  }, [navigate]);

  const login = useCallback(async (username: string, password: string) => {
    const next = await loginApi({ username, password });
    setUser(next);
    return next;
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutApi();
    } finally {
      setUser(null);
      navigate("/login");
    }
  }, [navigate]);

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string) => {
      const next = await changePasswordApi({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setUser(next);
      return next;
    },
    [],
  );

  const value = useMemo(
    () => ({ user, loading, login, logout, changePassword, refresh }),
    [user, loading, login, logout, changePassword, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

function AuthGateSpinner() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50">
      <Spinner />
    </div>
  );
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return <AuthGateSpinner />;
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (user.must_change_password) {
    return <Navigate to="/change-password" replace />;
  }
  return children;
}

export function GuestOnly({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return <AuthGateSpinner />;
  }
  if (user?.must_change_password) {
    return <Navigate to="/change-password" replace />;
  }
  if (user) {
    return <Navigate to="/" replace />;
  }
  return children;
}

export function RequireSession({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return <AuthGateSpinner />;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return children;
}
