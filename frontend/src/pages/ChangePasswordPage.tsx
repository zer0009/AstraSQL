import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { AstraLogo } from "../components/brand";
import { Button, Input } from "../components/ui";

export default function ChangePasswordPage() {
  const { user, changePassword, logout } = useAuth();
  const navigate = useNavigate();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await changePassword(currentPassword, newPassword);
      navigate("/", { replace: true });
    } catch (err) {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      setError(axiosErr.response?.data?.detail || "Could not change password.");
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
          <h1 className="text-base font-semibold text-zinc-900">
            Change password
          </h1>
          <p className="mt-1 text-xs text-zinc-500">
            Signed in as{" "}
            <span className="font-medium text-zinc-700">{user?.username}</span>.
            {user?.must_change_password
              ? " You must set a new password before using the app."
              : null}
          </p>

          <form className="mt-4 space-y-3" onSubmit={(e) => void onSubmit(e)}>
            <div>
              <label htmlFor="current-password" className="mb-1 block text-xs font-medium text-zinc-700">
                Current password
              </label>
              <Input
                id="current-password"
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                required
              />
            </div>
            <div>
              <label htmlFor="new-password" className="mb-1 block text-xs font-medium text-zinc-700">
                New password
              </label>
              <Input
                id="new-password"
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={12}
              />
              <p className="mt-1 text-[11px] text-zinc-400">
                At least 12 characters. Cannot be the default bootstrap password.
              </p>
            </div>
            <div>
              <label htmlFor="confirm-password" className="mb-1 block text-xs font-medium text-zinc-700">
                Confirm new password
              </label>
              <Input
                id="confirm-password"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                minLength={12}
              />
            </div>
            {error ? <p className="text-xs text-red-600">{error}</p> : null}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Saving…" : "Save password"}
            </Button>
          </form>

          <button
            type="button"
            className="mt-4 w-full text-center text-xs text-zinc-500 hover:text-zinc-800"
            onClick={() => void logout()}
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}
