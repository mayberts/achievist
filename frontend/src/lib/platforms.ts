export interface PlatformMeta {
  label: string;
  badge: string; // tailwind classes for the badge
  storeUrl?: (game: { platform_app_id: string; store_id: string | null }) => string;
}

export const PLATFORM_META: Record<string, PlatformMeta> = {
  steam: {
    label: "Steam",
    badge: "bg-[#1b2838] text-[#66c0f4] border-[#2a475e]",
    storeUrl: (g) => `https://store.steampowered.com/app/${g.platform_app_id}`,
  },
  xbox: {
    label: "Xbox",
    badge: "bg-[#0e3d0e] text-[#4ec94e] border-[#107c10]",
  },
  retroachievements: {
    label: "Retro",
    badge: "bg-[#1a1a2e] text-slate-300 border-[#333]",
    storeUrl: (g) => `https://retroachievements.org/game/${g.platform_app_id}`,
  },
  wargaming: {
    label: "Wargaming",
    badge: "bg-[#3a1a00] text-[#e8622a] border-[#c4380a]",
  },
  guildwars2: {
    label: "Guild Wars 2",
    badge: "bg-[#0d2a1a] text-[#c8392b] border-[#b01010]",
  },
  ubisoft: {
    label: "Ubisoft",
    badge: "bg-[#0a0a2e] text-[#3a9fe8] border-[#0070d1]",
  },
  epic: {
    label: "Epic Games",
    badge: "bg-[#121212] text-[#e6e6e6] border-[#3a3a3a]",
    storeUrl: (g) => (g.store_id ? `https://store.epicgames.com/p/${g.store_id}` : "https://store.epicgames.com/"),
  },
};

export function platformLabel(platform: string): string {
  return PLATFORM_META[platform]?.label ?? platform;
}
