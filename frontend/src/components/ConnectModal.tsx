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
        {schema.key === "psn" ? (
          <PSNFlow schema={schema} account={account} onConnected={onConnected} />
        ) : schema.key === "xbox" ? (
          <XboxFlow schema={schema} account={account} onConnected={onConnected} />
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

function PSNFlow({
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
    api.psnServiceStatus().then((s) => setSignedIn(s.signed_in)).catch(() => setSignedIn(false));
  }, []);

  if (signedIn === null) {
    return <div className="py-6 text-center text-muted">Checking…</div>;
  }

  if (signedIn && !forceLogin) {
    return (
      <div className="space-y-3">
        <FormFlow schema={schema} account={account} onConnected={onConnected} />
        <button
          onClick={() => setForceLogin(true)}
          className="text-xs text-muted underline hover:text-slate-300"
        >
          Re-sign in the backend PlayStation account
        </button>
      </div>
    );
  }

  return (
    <PSNServiceLogin
      onSignedIn={() => {
        setSignedIn(true);
        setForceLogin(false);
      }}
    />
  );
}

function PSNServiceLogin({ onSignedIn }: { onSignedIn: () => void }) {
  const [npsso, setNpsso] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setError(null);
    setBusy(true);
    try {
      await api.psnServiceTicket(npsso.trim());
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
        PlayStation needs one login token so the app can read public trophy profiles by
        Online ID. This is stored once and refreshed automatically.
      </p>
      <ol className="list-decimal space-y-1 pl-5 text-xs text-muted">
        <li>Log in at <span className="text-slate-300">playstation.com</span></li>
        <li>
          Visit{" "}
          <span className="text-slate-300">ca.account.sony.com/api/v1/ssocookie</span> in
          the same browser
        </li>
        <li>Copy the value of <span className="text-slate-300">"npsso"</span> from the JSON</li>
      </ol>
      <div>
        <label className="mb-1 block text-sm font-medium text-slate-300">npsso Token</label>
        <input
          value={npsso}
          onChange={(e) => setNpsso(e.target.value)}
          className="w-full rounded-lg border border-line bg-ink-900 px-3 py-2 text-xs text-slate-100 outline-none focus:border-accent-soft"
        />
      </div>
      {error && <p className="rounded-lg bg-red-950/50 px-3 py-2 text-sm text-red-300">{error}</p>}
      <button
        onClick={save}
        disabled={busy || !npsso.trim()}
        className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50"
      >
        {busy ? "Validating…" : "Save session"}
      </button>
    </div>
  );
}

function XboxFlow({
  schema,
  account,
  onConnected,
}: {
  schema: PlatformSchema;
  account?: Account;
  onConnected: () => void;
}) {
  const [mode, setMode] = useState<"choose" | "oauth">("choose");
  const [signedIn, setSignedIn] = useState<boolean | null>(null);

  useEffect(() => {
    api.xboxServiceStatus().then((s) => setSignedIn(s.signed_in)).catch(() => setSignedIn(false));
  }, []);

  if (mode === "oauth") {
    return <OAuthFlow schema={schema} onConnected={onConnected} />;
  }

  return (
    <div className="space-y-4">
      <p className="rounded-lg bg-ink-900 px-3 py-2 text-xs text-muted">
        Make sure your profile and achievement history are set to <span className="font-semibold text-slate-300">public</span>.
      </p>

      <div className={signedIn === false ? "opacity-60" : ""}>
        <FormFlow schema={schema} account={account} onConnected={onConnected} />
        {signedIn === false && (
          <p className="mt-2 text-xs text-warn">
            Sign in with Xbox first (below) so the app can read public profiles.
          </p>
        )}
      </div>

      <div className="flex items-center gap-3 text-xs text-faint">
        <span className="h-px flex-1 bg-line" /> or <span className="h-px flex-1 bg-line" />
      </div>

      <button
        onClick={() => setMode("oauth")}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#107c10] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#0e6b0e]"
      >
        Sign in with Xbox
      </button>
      <p className="text-center text-xs text-faint">
        Connects your own account and enables gamertag lookups.
      </p>
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
