import { useState } from "react";
import { Trophy } from "lucide-react";
import { api } from "../api";

export function LoginScreen({
  needsSetup,
  onAuthenticated,
}: {
  needsSetup: boolean;
  onAuthenticated: () => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (needsSetup) {
        await api.authSetup(username.trim(), password);
      } else {
        await api.login(username.trim(), password);
      }
      onAuthenticated();
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-card border border-line bg-ink-850 p-6 shadow-2xl">
        <div className="mb-6 flex items-center justify-center gap-2">
          <Trophy size={22} className="text-accent" />
          <span className="text-xl font-bold tracking-tight text-slate-100">Achievist</span>
        </div>

        <h1 className="mb-1 text-center text-lg font-semibold text-slate-100">
          {needsSetup ? "Create your account" : "Log in"}
        </h1>
        <p className="mb-5 text-center text-sm text-muted">
          {needsSetup
            ? "This creates the first account, with admin access to add accounts for the rest of your family."
            : "Welcome back."}
        </p>

        <form onSubmit={submit} className="space-y-3">
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-300">Username</label>
            <input
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-lg border border-line bg-ink-900 px-3 py-2 text-sm text-slate-100 outline-none focus:border-accent-soft"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-300">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-line bg-ink-900 px-3 py-2 text-sm text-slate-100 outline-none focus:border-accent-soft"
            />
            {needsSetup && <p className="mt-1 text-xs text-faint">At least 8 characters.</p>}
          </div>

          {error && <p className="rounded-lg bg-red-950/50 px-3 py-2 text-sm text-red-300">{error}</p>}

          <button
            type="submit"
            disabled={busy || !username.trim() || !password}
            className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50"
          >
            {busy ? "…" : needsSetup ? "Create account" : "Log in"}
          </button>
        </form>
      </div>
    </div>
  );
}
