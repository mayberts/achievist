import { useState } from "react";
import { X } from "lucide-react";
import { api } from "../api";
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
  const [saving, setSaving] = useState(false);
  const toast = useToast();

  async function save() {
    setSaving(true);
    try {
      const saved = await api.updateProfile({
        display_name: displayName.trim() || null,
        avatar_url: avatarUrl.trim() || null,
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
        className="flex max-h-[90vh] w-full max-w-sm flex-col overflow-y-auto rounded-card border border-line bg-ink-850 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line p-4">
          <h2 className="text-base font-semibold text-slate-100">Edit Profile</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-muted transition hover:bg-ink-800 hover:text-slate-200">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4 p-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted">Display name</label>
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Player"
              className="w-full rounded-lg border border-line bg-ink-900 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-faint"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted">Avatar URL</label>
            <input
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

          <button
            onClick={save}
            disabled={saving}
            className="w-full rounded-lg bg-accent px-3 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
