import { useEffect, useId, useRef } from "react";

/**
 * The parts of a dialog that are easy to leave out and impossible to work
 * without: Escape closes it, focus moves into it when it opens and back to
 * whatever opened it when it closes, and Tab stays inside while it is open.
 *
 * Every modal in the app could previously only be dismissed by clicking the
 * backdrop or the X — both mouse-only. Focus also stayed behind on the page
 * underneath, so a keyboard user tabbed through the whole page before ever
 * reaching the dialog they had just opened.
 *
 * Returns props to spread onto the dialog element, plus the id to hang on
 * its heading so screen readers announce the dialog by name.
 */
export function useModal(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  // Whatever had focus before the dialog opened, so it can be handed back.
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    opener.current = document.activeElement as HTMLElement | null;

    const node = ref.current;
    // Focus the dialog itself rather than its first field: announcing the
    // dialog's name first is more use than dropping you mid-form.
    node?.focus();

    function focusable(): HTMLElement[] {
      if (!node) return [];
      // The selector already excludes disabled and tabindex="-1" controls.
      // Deliberately no offsetParent check on top of it: offsetParent is null
      // for anything inside a position:fixed ancestor — which every modal
      // here is — so it would filter out the whole dialog.
      return Array.from(
        node.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute("hidden"));
    }

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;

      const items = focusable();
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;

      // Wrap at both ends, and catch the case where focus is on the dialog
      // container itself, which is not in the list.
      if (e.shiftKey && (active === first || active === node)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener.current?.focus?.();
    };
  }, [onClose]);

  return {
    titleId,
    dialogProps: {
      ref,
      role: "dialog" as const,
      "aria-modal": true,
      "aria-labelledby": titleId,
      tabIndex: -1,
    },
  };
}
