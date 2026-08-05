import { useEffect, useState } from "react";
import { DatabaseBackup, Download, Clock, FileJson, ImageDown, Trash2, UserPlus, Users } from "lucide-react";
import { api } from "../api";
import type { BackupInfo, User } from "../types";
import { fmtBytes, fmtRelative } from "../lib/format";
import { useToast } from "../components/Toast";

export function MaintenancePage({ isAdmin }: { isAdmin: boolean }) {
  return (
    <div>
      <div className="mb-2 text-lg font-semibold text-slate-100">Maintenance</div>
      <p className="mb-5 text-sm text-muted">
        App-wide background jobs: database backups and enrichment (cover art, time-to-beat).
      </p>

      {isAdmin && <FamilySection />}
      <MyDataSection />
      <CoversSection />
      <HltbSection />
      {isAdmin && <BackupsSection />}
    </div>
  );
}

function MyDataSection() {
  return (
    <div className="mb-8">
      <div className="mb-2 text-base font-semibold text-slate-100">My Data</div>
      <p className="mb-3 text-sm text-muted">
        Download your own library and unlocked achievements as JSON — just your data, no connected-account
        credentials and nothing from anyone else's library.
      </p>
      <div className="rounded-card border border-line bg-ink-850 p-4">
        <a
          href="/api/export"
          download
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-white transition hover:bg-accent/90"
        >
          <FileJson size={15} />
          Export my data
        </a>
      </div>
    </div>
  );
}

function FamilySection() {
  const [users, setUsers] = useState<User[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const toast = useToast();

  async function refresh() {
    setUsers(await api.users());
  }

  useEffect(() => {
    refresh();
  }, []);

  async function addUser(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    try {
      await api.createUser({
        username: username.trim(),
        password,
        display_name: displayName.trim() || undefined,
      });
      toast.success(`${username} can now log in`);
      setUsername("");
      setPassword("");
      setDisplayName("");
      await refresh();
    } catch (err) {
      toast.error(String(err instanceof Error ? err.message : err));
    } finally {
      setCreating(false);
    }
  }

  async function remove(u: User) {
    if (!confirm(`Delete ${u.username}'s account? Their games, achievements, and connected accounts go with it.`)) return;
    try {
      await api.deleteUser(u.id);
      toast.success(`${u.username} deleted`);
      refresh();
    } catch (err) {
      toast.error(String(err instanceof Error ? err.message : err));
    }
  }

  return (
    <div className="mb-8">
      <div className="mb-2 text-base font-semibold text-slate-100">Family Accounts</div>
      <p className="mb-3 text-sm text-muted">
        Each person gets their own login and their own separate library — accounts they connect
        aren't shared with anyone else.
      </p>

      <div className="rounded-card border border-line bg-ink-850 p-4">
        <div className="mb-4 space-y-2">
          {users === null ? (
            <div className="text-sm text-faint">Loading…</div>
          ) : (
            users.map((u) => (
              <div key={u.id} className="flex items-center justify-between gap-3 rounded-lg bg-ink-900/50 px-3 py-2">
                <div className="flex min-w-0 items-center gap-2">
                  <Users size={14} className="flex-shrink-0 text-faint" />
                  <span className="truncate text-sm text-slate-200">{u.display_name || u.username}</span>
                  {u.is_admin && (
                    <span className="rounded-md bg-accent/20 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
                      Admin
                    </span>
                  )}
                </div>
                <button
                  onClick={() => remove(u)}
                  className="inline-flex flex-shrink-0 items-center rounded-lg border border-line bg-ink-800 px-2 py-1 text-xs text-red-400 transition hover:bg-red-950/40"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))
          )}
        </div>

        <form onSubmit={addUser} className="grid gap-2 sm:grid-cols-3">
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Username"
            className="rounded-lg border border-line bg-ink-900 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-faint focus:border-accent-soft"
          />
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Display name (optional)"
            className="rounded-lg border border-line bg-ink-900 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-faint focus:border-accent-soft"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password (8+ characters)"
            className="rounded-lg border border-line bg-ink-900 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-faint focus:border-accent-soft"
          />
          <button
            type="submit"
            disabled={creating || !username.trim() || password.length < 8}
            className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50 sm:col-span-3"
          >
            <UserPlus size={15} />
            {creating ? "Creating…" : "Add family member"}
          </button>
        </form>
      </div>
    </div>
  );
}

function HltbSection() {
  const [refreshing, setRefreshing] = useState(false);
  const toast = useToast();

  async function refreshHltb() {
    setRefreshing(true);
    try {
      await api.hltbRefresh();
      toast.info("Time-to-beat refresh started — this can take a few minutes for a large library.");
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
    } finally {
      setTimeout(() => setRefreshing(false), 1500);
    }
  }

  return (
    <div className="mb-8">
      <div className="mb-2 text-base font-semibold text-slate-100">Time to Beat</div>
      <p className="mb-3 text-sm text-muted">
        Re-fetch every game's HowLongToBeat data from scratch. Useful after a name-matching fix, or
        if a batch of games show no time-to-beat despite having one on HowLongToBeat.com.
      </p>
      <div className="rounded-card border border-line bg-ink-850 p-4">
        <button
          onClick={refreshHltb}
          disabled={refreshing}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50"
        >
          <Clock size={15} className={refreshing ? "animate-pulse" : ""} />
          {refreshing ? "Starting…" : "Refresh time to beat"}
        </button>
      </div>
    </div>
  );
}

function CoversSection() {
  const [refreshing, setRefreshing] = useState(false);
  const toast = useToast();

  async function refreshCovers() {
    setRefreshing(true);
    try {
      await api.sgdbRefresh(true);
      toast.info("Cover refresh started — this can take a few minutes for a large library.");
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
    } finally {
      setTimeout(() => setRefreshing(false), 1500);
    }
  }

  return (
    <div className="mb-8">
      <div className="mb-2 text-base font-semibold text-slate-100">Cover Art</div>
      <p className="mb-3 text-sm text-muted">
        Re-fetch every game's cover art from SteamGridDB from scratch — useful after a change to
        which art is preferred, or if a batch of covers still look wrong. Games with a manually
        chosen cover (via Change Cover on a game's detail page) get overwritten too.
      </p>
      <div className="rounded-card border border-line bg-ink-850 p-4">
        <button
          onClick={refreshCovers}
          disabled={refreshing}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50"
        >
          <ImageDown size={15} className={refreshing ? "animate-pulse" : ""} />
          {refreshing ? "Starting…" : "Refresh all covers"}
        </button>
      </div>
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
    <div>
      <div className="mb-2 text-base font-semibold text-slate-100">Backups</div>
      <p className="mb-3 text-sm text-muted">
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
