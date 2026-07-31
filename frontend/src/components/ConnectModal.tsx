import { useEffect, useState } from "react";
import { X } from "lucide-react";
import type { Account, PlatformSchema } from "../types";
import { api } from "../api";

export function ConnectModal({
  schema,
  account,
  onClose,
  onConnected,
}: {
  schema: PlatformSchema;
  account?: Account;
  onClose: () => void;
  onConnected: () => void;
}) {
  const editing = !!account;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-card border border-line bg-ink-850 p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-100">
            {editing ? "Edit" : "Connect"} {schema.label}
          </h2>
          <button onClick={onClose} className="text-muted hover:text-slate-200">
            <X size={18} />
          </button>
        </div>
        {schema.key === "ubisoft" ? (
          <UbisoftFlow schema={schema} account={account} onConnected={onConnected} />
        ) : schema.auth_type === "oauth" ? (
          <OAuthFlow schema={schema} onConnected={onConnected} />
        ) : (
          <FormFlow schema={schema} account={account} onConnected={onConnected} />
        )}
      </div>
    </div>
  );
}

function FormFlow({
  schema,
  account,
  onConnected,
}: {
  schema: PlatformSchema;
  account?: Account;
  onConnected: () => void;
}) {
  // Prefill non-secret fields (and external_id) when editing; secrets stay blank.
  const [values, setValues] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    if (account) {
      for (const f of schema.fields) {
        if (f.secret) continue;
        if (f.name === "external_id") init[f.name] = account.external_id;
        else if (account.credentials[f.name] != null) init[f.name] = account.credentials[f.name];
      }
    }
    return init;
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setError(null);
    setBusy(true);
    try {
      await api.connectAccount({ platform: schema.key, credentials: values });
      onConnected();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      {schema.fields.map((f) => (
        <div key={f.name}>
          <label className="mb-1 block text-sm font-medium text-slate-300">
            {f.label}
            {f.required && <span className="text-warn"> *</span>}
          </label>
          {f.type === "select" ? (
            <select
              value={values[f.name] ?? f.options?.[0] ?? ""}
              onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
              className="w-full rounded-lg border border-line bg-ink-900 px-3 py-2 text-sm text-slate-100 outline-none focus:border-accent-soft"
            >
              {f.options?.map((o) => (
                <option key={o} value={o}>{o}</option>
              ))}
            </select>
          ) : (
            <input
              type={f.type === "password" ? "password" : "text"}
              value={values[f.name] ?? ""}
              placeholder={account && f.secret ? "Leave blank to keep current" : undefined}
              onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
              className="w-full rounded-lg border border-line bg-ink-900 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-faint focus:border-accent-soft"
            />
          )}
          {f.help && <p className="mt-1 text-xs text-faint">{f.help}</p>}
        </div>
      ))}
      {error && <p className="rounded-lg bg-red-950/50 px-3 py-2 text-sm text-red-300">{error}</p>}
      <button
        onClick={submit}
        disabled={busy}
        className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50"
      >
        {busy ? "Connecting…" : "Connect"}
      </button>
    </div>
  );
}

function UbisoftFlow({
  schema,
  account,
  onConnected,
}: {
  schema: PlatformSchema;
  account?: Account;
  onConnected: () => void;
}) {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [forceLogin, setForceLogin] = useState(false);

  useEffect(() => {
    api.ubisoftServiceStatus().then((s) => setSignedIn(s.signed_in)).catch(() => setSignedIn(false));
  }, []);

  if (signedIn === null) {
    return <div className="py-6 text-center text-muted">Checking…</div>;
  }

  // Once the backend service account is signed in, an account is just a username.
  if (signedIn && !forceLogin) {
    return (
      <div className="space-y-3">
        <FormFlow schema={schema} account={account} onConnected={onConnected} />
        <button
          onClick={() => setForceLogin(true)}
          className="text-xs text-muted underline hover:text-slate-300"
        >
          Re-sign in the backend Ubisoft account
        </button>
      </div>
    );
  }

  return (
    <UbisoftServiceLogin
      onSignedIn={() => {
        setSignedIn(true);
        setForceLogin(false);
      }}
    />
  );
}

function UbisoftServiceLogin({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [twoFa, setTwoFa] = useState<{ ticket: string; method?: string } | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function login() {
    setError(null);
    setBusy(true);
    try {
      const r = await api.ubisoftServiceLogin({ email, password });
      if (r.status === "2fa_required" && r.two_factor_ticket) {
        setTwoFa({ ticket: r.two_factor_ticket, method: r.method });
      } else {
        onSignedIn();
      }
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    if (!twoFa) return;
    setError(null);
    setBusy(true);
    try {
      await api.ubisoftServiceVerify({ ticket: twoFa.ticket, code });
      onSignedIn();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <p className="rounded-lg bg-ink-900 px-3 py-2 text-xs text-muted">
        Ubisoft needs one backend sign-in so the app can read public profiles by username (this is
        stored once and reused). Sign in with a Ubisoft account below.
      </p>

      {!twoFa ? (
        <>
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-300">Ubisoft Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
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
          </div>
          {error && <p className="rounded-lg bg-red-950/50 px-3 py-2 text-sm text-red-300">{error}</p>}
          <button
            onClick={login}
            disabled={busy || !email || !password}
            className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </>
      ) : (
        <>
          <div>
            <label className="mb-1 block text-sm font-medium text-slate-300">
              Two-factor code {twoFa.method ? `(${twoFa.method})` : ""}
            </label>
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="w-full rounded-lg border border-line bg-ink-900 px-3 py-2 text-sm tracking-widest text-slate-100 outline-none focus:border-accent-soft"
            />
          </div>
          {error && <p className="rounded-lg bg-red-950/50 px-3 py-2 text-sm text-red-300">{error}</p>}
          <button
            onClick={verify}
            disabled={busy || !code}
            className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50"
          >
            {busy ? "Verifying…" : "Verify"}
          </button>
        </>
      )}
    </div>
  );
}

function OAuthFlow({ schema, onConnected }: { schema: PlatformSchema; onConnected: () => void }) {
  const [flow, setFlow] = useState<{ user_code: string; verification_uri: string; device_code: string } | null>(null);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setError(null);
    setStatus("Starting…");
    try {
      const r = await fetch("/api/xbox-setup");
      if (!r.ok) throw new Error((await r.json()).detail);
      const data = await r.json();
      setFlow(data);
      setStatus("Waiting for sign-in…");
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setStatus("");
    }
  }

  useEffect(() => {
    if (!flow) return;
    let stop = false;
    const poll = async () => {
      while (!stop) {
        await new Promise((res) => setTimeout(res, 5000));
        try {
          const r = await fetch(`/api/xbox-setup-poll?device_code=${flow.device_code}`);
          const data = await r.json();
          if (data.status === "done") {
            // register the account so it shows in the DB-backed list
            await api.connectAccount({ platform: schema.key, credentials: {} }).catch(() => {});
            onConnected();
            return;
          }
        } catch {
          /* keep polling */
        }
      }
    };
    poll();
    return () => {
      stop = true;
    };
  }, [flow, schema.key, onConnected]);

  if (!flow) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted">
          Xbox uses Microsoft sign-in. Click below to get a code, then sign in on microsoft.com.
        </p>
        {error && <p className="rounded-lg bg-red-950/50 px-3 py-2 text-sm text-red-300">{error}</p>}
        <button
          onClick={start}
          className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-accent/90"
        >
          Start Xbox sign-in
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3 text-center">
      <p className="text-sm text-muted">Go to</p>
      <a
        href={flow.verification_uri}
        target="_blank"
        rel="noopener"
        className="block text-accent underline"
      >
        {flow.verification_uri}
      </a>
      <p className="text-sm text-muted">and enter this code:</p>
      <div className="rounded-lg bg-ink-900 py-3 text-2xl font-bold tracking-widest text-slate-100">
        {flow.user_code}
      </div>
      <p className="text-sm text-faint">{status}</p>
    </div>
  );
}
