import { PLATFORM_META, platformLabel } from "../lib/platforms";

export function PlatformBadge({ platform }: { platform: string }) {
  const meta = PLATFORM_META[platform];
  const cls = meta?.badge ?? "bg-ink-700 text-slate-300 border-ink-600";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-semibold ${cls}`}
    >
      <span
        className="h-1.5 w-1.5 flex-shrink-0 rounded-full"
        style={{ background: meta?.dot ?? "#9ca3af" }}
      />
      {platformLabel(platform)}
    </span>
  );
}
