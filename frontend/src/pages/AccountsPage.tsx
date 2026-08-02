import { useEffect, useState } from "react";
import { RefreshCw, Trash2, Plus, CheckCircle2, AlertCircle, Download, DatabaseBackup } from "lucide-react";
import { api } from "../api";
import type { Account, BackupInfo, PlatformSchema } from "../types";
import { platformLabel } from "../lib/platforms";
import { fmtBytes, fmtRelative } from "../lib/format";
import { ConnectModal } from "../components/ConnectModal";
import { AccountCardSkeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";

export function AccountsPage() {
  const [schemas, setSchemas] = useState<PlatformSchema[]>([]);
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [connecting, setConnecting] = useState<PlatformSchema | null>(null);
  const [editingAccount, setEditingAccount] = useState<Account | undefined>(undefined);
  const [syncing, setSyncing] = useState<number | null>(null);
  const toast = useToast();

  async function refresh() {
    const [s, a] = await Promise.all([api.platforms(), api.accounts()]);
    setSchemas(s);
    setAccounts(a);
  }

  useEffect(() => {
    refresh();
  }, []);

  const byPlatform = new Map((accounts ?? []).map((a) => [a.platform, a]));

  async function disconnect(id: number, label: string) {
    if (!confirm("Disconnect this account? Its synced games and achievements will be removed.")) return;
    try {
      await api.disconnectAccount(id);
      toast.success(`${label} disconnected`);
      refresh();
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
    }
  }

  async function syncOne(id: number, label: string) {
    setSyncing(id);
    try {
      await api.syncAccount(id);
      toast.info(`Syncing ${label}…`);
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
    } finally {
      setTimeout(() => setSyncing(null), 1500);
    }
  }

  return (
    <div>
      <div className="mb-2 text-lg font-semibold text-slate-100">Gaming Accounts</div>
      <p className="mb-5 text-sm text-muted">Connect and manage the platforms you sync achievements from.</p>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {accounts === null
          ? Array.from({ length: 6 }).map((_, i) => <AccountCardSkeleton key={i} />)
          : schemas.map((schema) => {
          const acct = byPlatform.get(schema.key);
          return (
            <div key={schema.key} className="rounded-card border border-line bg-ink-850 p-4">
              <div className="flex items-center justify-between">
                <div className="font-semibold text-slate-100">{platformLabel(schema.key)}</div>
                {acct ? (
                  acct.status === "error" ? (
                    <span className="inline-flex items-center gap-1 text-xs text-red-400">
                      <AlertCircle size={13} /> Error
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-xs text-good">
                      <CheckCircle2 size={13} /> Connected
                    </span>
                  )
                ) : (
                  <span className="text-xs text-faint">Not connected</span>
                )}
              </div>

              {acct ? (
                <>
                  <div className="mt-3 text-sm text-slate-300">{acct.display_name || acct.external_id}</div>
                  <div className="mt-0.5 text-xs text-faint">
                    Synced {fmtRelative(acct.last_synced_at)}
                  </div>
                  {acct.status === "error" && acct.last_error && (
                    <div className="mt-2 truncate text-xs text-red-400" title={acct.last_error}>
                      {acct.last_error}
                    </div>
                  )}
                  <div className="mt-3 flex gap-2">
                    <button
                      onClick={() => syncOne(acct.id, platformLabel(schema.key))}
                      disabled={syncing === acct.id}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-ink-800 px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:bg-ink-700 disabled:opacity-50"
                    >
                      <RefreshCw size={13} className={syncing === acct.id ? "animate-spin" : ""} />
                      Sync
                    </button>
                    <button
                      onClick={() => {
                        setEditingAccount(acct);
                        setConnecting(schema);
                      }}
                      className="rounded-lg border border-line bg-ink-800 px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:bg-ink-700"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => disconnect(acct.id, platformLabel(schema.key))}
                      className="ml-auto inline-flex items-center rounded-lg border border-line bg-ink-800 px-2.5 py-1.5 text-xs text-red-400 transition hover:bg-red-950/40"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </>
              ) : (
                <button
                  onClick={() => {
                    setEditingAccount(undefined);
                    setConnecting(schema);
                  }}
                  className="mt-4 inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-white transition hover:bg-accent/90"
                >
                  <Plus size={15} /> Connect
                </button>
              )}
            </div>
          );
        })}
      </div>

      {connecting && (
        <ConnectModal
          schema={connecting}
          account={editingAccount}
          onClose={() => {
            setConnecting(null);
            setEditingAccount(undefined);
          }}
          onConnected={() => {
            const label = platformLabel(connecting.key);
            setConnecting(null);
            setEditingAccount(undefined);
            toast.success(`${label} connected`);
            refresh();
          }}
        />
      )}

      <BackupsSection />
    </div>
  );
}

function BackupsSection() {
  const [backups, setBackups] = useState<BackupInfo[] | null>(null);
  const [keepCount, setKeepCount] = useState(14);
  const [intervalHours, setIntervalHours] = useState(24);
  const [creating, setCreating] = useState(false);
  const toast = useToast();

  async function refresh() {
    const r = await api.backups();
    setBackups(r.backups);
    setKeepCount(r.keep_count);
    setIntervalHours(r.interval_hours);
  }

  useEffect(() => {
    refresh();
  }, []);

  async function createNow() {
    setCreating(true);
    try {
      await api.createBackup();
      toast.success("Backup created");
      await refresh();
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
    } finally {
      setCreating(false);
    }
  }

  async function remove(filename: string) {
    if (!confirm(`Delete backup ${filename}?`)) return;
    try {
      await api.deleteBackup(filename);
      toast.success("Backup deleted");
      refresh();
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
    }
  }

  return (
    <div className="mt-8">
      <div className="mb-2 text-lg font-semibold text-slate-100">Backups</div>
      <p className="mb-5 text-sm text-muted">
        A full database dump runs automatically every {intervalHours}h, keeping the most recent{" "}
        {keepCount}. Backups include connected-account credentials — keep downloaded files
        somewhere safe.
      </p>

      <div className="rounded-card border border-line bg-ink-850 p-4">
        <button
          onClick={createNow}
          disabled={creating}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50"
        >
          <DatabaseBackup size={15} className={creating ? "animate-pulse" : ""} />
          {creating ? "Creating…" : "Create backup now"}
        </button>

        <div className="mt-4 divide-y divide-line">
          {backups === null ? (
            <div className="py-2 text-sm text-faint">Loading…</div>
          ) : backups.length === 0 ? (
            <div className="py-2 text-sm text-faint">No backups yet.</div>
          ) : (
            backups.map((b) => (
              <div key={b.filename} className="flex items-center justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <div className="truncate text-sm text-slate-200">{b.filename}</div>
                  <div className="text-xs text-faint">
                    {fmtRelative(b.created_at)} · {fmtBytes(b.size_bytes)}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <a
                    href={`/api/backups/${encodeURIComponent(b.filename)}`}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-ink-800 px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:bg-ink-700"
                    download
                  >
                    <Download size={13} />
                    Download
                  </a>
                  <button
                    onClick={() => remove(b.filename)}
                    className="inline-flex items-center rounded-lg border border-line bg-ink-800 px-2.5 py-1.5 text-xs text-red-400 transition hover:bg-red-950/40"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
