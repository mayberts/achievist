export interface PlatformMeta {
  label: string;
  badge: string; // tailwind classes for the badge
  dot: string; // hex color for the identifying dot shown in badges/cards
  storeUrl?: (game: { platform_app_id: string; store_id: string | null }) => string;
}

export const PLATFORM_META: Record<string, PlatformMeta> = {
  steam: {
    label: "Steam",
    badge: "bg-[#1b2838] text-[#66c0f4] border-[#2a475e]",
    dot: "#66c0f4",
    storeUrl: (g) => `https://store.steampowered.com/app/${g.platform_app_id}`,
  },
  xbox: {
    label: "Xbox",
    badge: "bg-[#0e3d0e] text-[#4ec94e] border-[#107c10]",
    dot: "#4ec94e",
  },
  retroachievements: {
    label: "Retro",
    badge: "bg-[#1a1a2e] text-slate-300 border-[#333]",
    dot: "#9ca3af",
    storeUrl: (g) => `https://retroachievements.org/game/${g.platform_app_id}`,
  },
  wargaming: {
    label: "Wargaming",
    badge: "bg-[#3a1a00] text-[#e8622a] border-[#c4380a]",
    dot: "#e8622a",
  },
  guildwars2: {
    label: "Guild Wars 2",
    badge: "bg-[#0d2a1a] text-[#c8392b] border-[#b01010]",
    dot: "#c8392b",
  },
  ubisoft: {
    label: "Ubisoft",
    badge: "bg-[#0a0a2e] text-[#3a9fe8] border-[#0070d1]",
    dot: "#3a9fe8",
  },
  epic: {
    label: "Epic Games",
    badge: "bg-[#121212] text-[#e6e6e6] border-[#3a3a3a]",
    dot: "#e6e6e6",
    storeUrl: (g) => (g.store_id ? `https://store.epicgames.com/p/${g.store_id}` : "https://store.epicgames.com/"),
  },
  psn: {
    label: "PlayStation",
    badge: "bg-[#00184a] text-[#66c0f4] border-[#003791]",
    dot: "#66c0f4",
  },
  ea: {
    label: "EA App",
    badge: "bg-[#0a0a0a] text-[#ff4747] border-[#ff4747]",
    dot: "#ff4747",
  },
  googleplay: {
    label: "Google Play",
    badge: "bg-[#01875f]/20 text-[#01875f] border-[#01875f]",
    dot: "#01875f",
  },
  gog: {
    label: "GOG",
    badge: "bg-[#5a1f8a]/20 text-[#a855f7] border-[#a855f7]",
    dot: "#a855f7",
  },
};

export function platformLabel(platform: string): string {
  return PLATFORM_META[platform]?.label ?? platform;
}
