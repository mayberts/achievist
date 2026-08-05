import { useEffect, useState } from "react";
import { api, onProfileUpdated } from "../api";

// Sits behind the whole app at -z-20, below GameDetailPage's own per-game
// backdrop (-z-10) so a game's own art still wins on its detail page.
export function AppBackground() {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    api.profile()
      .then((p) => setUrl(p.background_url))
      .catch(() => setUrl(null));
    return onProfileUpdated((p) => setUrl(p.background_url));
  }, []);

  if (!url) return null;

  return (
    <>
      <div
        className="fixed inset-0 -z-20 bg-cover bg-center opacity-40"
        style={{ backgroundImage: `url("${url.replace(/"/g, '\\"')}")` }}
      />
      <div className="fixed inset-0 -z-20 bg-gradient-to-b from-ink-950/60 via-ink-950/80 to-ink-950" />
    </>
  );
}
