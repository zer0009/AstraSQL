import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { AstraLogo } from "../components/brand";
import { Button, Input } from "../components/ui";
import { getAuthStatus } from "../services/api";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showDefaults, setShowDefaults] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void getAuthStatus()
      .then((status) => {
        if (!cancelled) setShowDefaults(!status.setup_complete);
      })
      .catch(() => {
        if (!cancelled) setShowDefaults(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const user = await login(username.trim(), password);
      if (user.must_change_password) {
        navigate("/change-password", { replace: true });
      } else {
        navigate("/", { replace: true });
      }
    } catch (err) {
      const axiosErr = err as {
        response?: { status?: number; data?: { detail?: string } };
      };
      if (axiosErr.response?.status === 423) {
        setError(
          axiosErr.response.data?.detail ||
            "Account locked. Try again later.",
        );
      } else {
        setError(
          axiosErr.response?.data?.detail || "Invalid username or password.",
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex justify-center">
          <AstraLogo size={32} />
        </div>
        <div className="rounded-lg border border-zinc-200 bg-white p-6 shadow-sm">
          <h1 className="text-base font-semibold text-zinc-900">Sign in</h1>
          <p className="mt-1 text-xs text-zinc-500">
            Use the local admin account to access AstraSQL.
          </p>

          {showDefaults ? (
            <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              First setup is not complete. Sign in as{" "}
              <span className="font-medium">admin</span> /{" "}
              <span className="font-medium">AstraSQL-change-me</span>, then
              change the password immediately.
            </div>
          ) : null}

          <form className="mt-4 space-y-3" onSubmit={(e) => void onSubmit(e)}>
            <div>
              <label htmlFor="login-username" className="mb-1 block text-xs font-medium text-zinc-700">
                Username
              </label>
              <Input
                id="login-username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </div>
            <div>
              <label htmlFor="login-password" className="mb-1 block text-xs font-medium text-zinc-700">
                Password
              </label>
              <Input
                id="login-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error ? <p className="text-xs text-red-600">{error}</p> : null}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
