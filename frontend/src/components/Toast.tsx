import { createContext, useCallback, useContext, useRef, useState } from "react";
import { CheckCircle2, XCircle, Info, Trophy, X } from "lucide-react";

type ToastKind = "success" | "error" | "info" | "achievement";

interface ToastOpts {
  subtitle?: string;
  icon?: string | null;
  durationMs?: number;
}

interface ToastItem extends ToastOpts {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  push: (kind: ToastKind, message: string, opts?: ToastOpts) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return {
    success: (msg: string) => ctx.push("success", msg),
    error: (msg: string) => ctx.push("error", msg),
    info: (msg: string) => ctx.push("info", msg),
    achievement: (opts: { name: string; subtitle: string; icon?: string | null }) =>
      ctx.push("achievement", opts.name, { subtitle: opts.subtitle, icon: opts.icon, durationMs: 7000 }),
  };
}

const ICONS: Record<ToastKind, React.ReactNode> = {
  success: <CheckCircle2 size={16} className="text-good" />,
  error: <XCircle size={16} className="text-red-400" />,
  info: <Info size={16} className="text-accent" />,
  achievement: <Trophy size={16} className="text-warn" />,
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const idRef = useRef(0);

  const push = useCallback((kind: ToastKind, message: string, opts?: ToastOpts) => {
    const id = ++idRef.current;
    setItems((prev) => [...prev, { id, kind, message, ...opts }]);
    window.setTimeout(() => {
      setItems((prev) => prev.filter((t) => t.id !== id));
    }, opts?.durationMs ?? 5000);
  }, []);

  const dismiss = (id: number) => setItems((prev) => prev.filter((t) => t.id !== id));

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed bottom-6 left-1/2 z-[100] flex w-full max-w-sm -translate-x-1/2 flex-col gap-2 px-4"
      >
        {items.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto flex items-start gap-2.5 rounded-lg border p-3 shadow-lg ${
              t.kind === "achievement" ? "border-warn/40 bg-ink-850" : "border-line bg-ink-850"
            }`}
          >
            {t.kind === "achievement" && t.icon ? (
              <img src={t.icon} alt="" className="mt-0.5 h-9 w-9 flex-shrink-0 rounded-md object-cover ring-1 ring-black/40" />
            ) : (
              <span className="mt-0.5 flex-shrink-0">{ICONS[t.kind]}</span>
            )}
            <span className="min-w-0 flex-1">
              {t.kind === "achievement" && (
                <div className="text-[10px] font-semibold uppercase tracking-wide text-warn">Achievement Unlocked</div>
              )}
              <div className="text-sm text-slate-200">{t.message}</div>
              {t.subtitle && <div className="text-xs text-faint">{t.subtitle}</div>}
            </span>
            <button
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
              className="flex-shrink-0 text-faint hover:text-slate-300"
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
