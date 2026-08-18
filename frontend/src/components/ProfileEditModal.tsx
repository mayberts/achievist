import { useState } from "react";
import { FileJson, X } from "lucide-react";
import { api } from "../api";
import { useModal } from "../lib/useModal";
import type { Profile } from "../types";
import { useToast } from "./Toast";

export function ProfileEditModal({
  profile,
  onClose,
  onSaved,
}: {
  profile: Profile;
  onClose: () => void;
  onSaved: (p: Profile) => void;
}) {
  const [displayName, setDisplayName] = useState(profile.display_name ?? "");
  const [avatarUrl, setAvatarUrl] = useState(profile.avatar_url ?? "");
  const [backgroundUrl, setBackgroundUrl] = useState(profile.background_url ?? "");
  const [shareStats, setShareStats] = useState(profile.share_stats);
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  const { titleId, dialogProps } = useModal(onClose);

  async function save() {
    setSaving(true);
    try {
      const saved = await api.updateProfile({
        display_name: displayName.trim() || null,
        avatar_url: avatarUrl.trim() || null,
        background_url: backgroundUrl.trim() || null,
        share_stats: shareStats,
      });
      toast.success("Profile updated");
      onSaved(saved);
      onClose();
    } catch (e) {
      toast.error(String(e instanceof Error ? e.message : e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4"
      onClick={(e) => {
        e.stopPropagation();
        onClose();
      }}
    >
      <div
        {...dialogProps}
        className="flex max-h-[90vh] w-full max-w-sm flex-col overflow-y-auto rounded-card border border-line bg-ink-850 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line p-4">
          <h2 id={titleId} className="text-base font-semibold text-slate-100">Edit Profile</h2>
          <button
            onClick={onClose}
            aria-label="Close profile editor"
            className="rounded-lg p-1.5 text-muted transition hover:bg-ink-800 hover:text-slate-200"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4 p-4">
          <div>
            <label htmlFor="profile-display-name" className="mb-1 block text-xs font-medium text-muted">Display name</label>
            <input
              id="profile-display-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Player"
              className="w-full rounded-lg border border-line bg-ink-900 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-faint"
            />
          </div>
          <div>
            <label htmlFor="profile-avatar-url" className="mb-1 block text-xs font-medium text-muted">Avatar URL</label>
            <input
              id="profile-avatar-url"
              value={avatarUrl}
              onChange={(e) => setAvatarUrl(e.target.value)}
              placeholder="https://…"
              className="w-full rounded-lg border border-line bg-ink-900 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-faint"
            />
            {avatarUrl.trim() && (
              <img
                src={avatarUrl.trim()}
                alt=""
                className="mt-2 h-14 w-14 rounded-full object-cover ring-1 ring-black/40"
                onError={(e) => (e.currentTarget.style.visibility = "hidden")}
                onLoad={(e) => (e.currentTarget.style.visibility = "visible")}
              />
            )}
          </div>
          <div>
            <label htmlFor="profile-background-url" className="mb-1 block text-xs font-medium text-muted">Background image URL</label>
            <input
              id="profile-background-url"
              value={backgroundUrl}
              onChange={(e) => setBackgroundUrl(e.target.value)}
              placeholder="https://…"
              className="w-full rounded-lg border border-line bg-ink-900 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-faint"
            />
            <p className="mt-1 text-xs text-faint">Shown behind every page. A game's own art still takes over on its detail page.</p>
            {backgroundUrl.trim() && (
              <img
                src={backgroundUrl.trim()}
                alt=""
                className="mt-2 h-16 w-full rounded-lg object-cover ring-1 ring-black/40"
                onError={(e) => (e.currentTarget.style.visibility = "hidden")}
                onLoad={(e) => (e.currentTarget.style.visibility = "visible")}
              />
            )}
          </div>

          <label className="flex items-start gap-2 rounded-lg border border-line bg-ink-900 px-3 py-2.5">
            <input
              type="checkbox"
              checked={shareStats}
              onChange={(e) => setShareStats(e.target.checked)}
              className="mt-0.5 h-4 w-4 flex-shrink-0 accent-accent"
            />
            <span className="text-sm text-slate-200">
              Compare achievements with family
              <span className="mt-0.5 block text-xs text-muted">
                Shows your Achievist Points and stats on the family Leaderboard.
              </span>
            </span>
          </label>

          <button
            onClick={save}
            disabled={saving}
            className="w-full rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save"}
          </button>

          {/* Export lives here, next to your name and your sharing setting,
              because it is your data. It used to sit on the Maintenance tab
              among app-wide admin jobs, which both hid it from the people it
              belongs to and kept that tab visible to everyone. */}
          <div className="border-t border-line pt-4">
            <div className="mb-1 text-xs font-medium text-muted">Your data</div>
            <a
              href="/api/export"
              download
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-ink-900 px-3 py-2 text-sm font-medium text-slate-200 transition hover:bg-ink-800"
            >
              <FileJson size={15} className="text-faint" />
              Export my data
            </a>
            <p className="mt-1.5 text-xs text-faint">
              Your library and unlocked achievements as JSON — just yours, with no connected-account
              credentials and nothing from anyone else.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
