import { createContext, useCallback, useContext, useRef, useState } from "react";
import { CheckCircle2, XCircle, Info, X } from "lucide-react";

type ToastKind = "success" | "error" | "info";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  push: (kind: ToastKind, message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return {
    success: (msg: string) => ctx.push("success", msg),
    error: (msg: string) => ctx.push("error", msg),
    info: (msg: string) => ctx.push("info", msg),
  };
}

const ICONS: Record<ToastKind, React.ReactNode> = {
  success: <CheckCircle2 size={16} className="text-good" />,
  error: <XCircle size={16} className="text-red-400" />,
  info: <Info size={16} className="text-accent" />,
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const idRef = useRef(0);

  const push = useCallback((kind: ToastKind, message: string) => {
    const id = ++idRef.current;
    setItems((prev) => [...prev, { id, kind, message }]);
    window.setTimeout(() => {
      setItems((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  const dismiss = (id: number) => setItems((prev) => prev.filter((t) => t.id !== id));

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed bottom-6 left-1/2 z-[100] flex w-full max-w-sm -translate-x-1/2 flex-col gap-2 px-4">
        {items.map((t) => (
          <div
            key={t.id}
            className="pointer-events-auto flex items-start gap-2 rounded-lg border border-line bg-ink-850 p-3 shadow-lg"
          >
            <span className="mt-0.5 flex-shrink-0">{ICONS[t.kind]}</span>
            <span className="min-w-0 flex-1 text-sm text-slate-200">{t.message}</span>
            <button onClick={() => dismiss(t.id)} className="flex-shrink-0 text-faint hover:text-slate-300">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
