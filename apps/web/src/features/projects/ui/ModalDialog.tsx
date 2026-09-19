"use client";

import { useEffect, useRef, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

interface ModalDialogProps {
  /** Id of the element that names the dialog. */
  labelledBy: string;
  /** What opened the dialog; the focus goes back to it on close. */
  opener: RefObject<HTMLElement | null>;
  /** Escape or a click on the backdrop. Not called while `dismissable` is false. */
  onDismiss: () => void;
  dismissable?: boolean;
  backdropTestId?: string;
  children: ReactNode;
}

/**
 * The design's centred modal (backdrop, panel surface, `bt-modal` entrance) with the behaviour
 * a modal owes the keyboard: focus moves in, Tab stays in, Escape dismisses, and focus goes
 * back to whatever opened it. Rendered in a portal so an ancestor that hides (the sidebar
 * drawer on small screens) cannot take the dialog with it.
 */
export function ModalDialog({ labelledBy, opener, onDismiss, dismissable = true, backdropTestId, children }: ModalDialogProps) {
  const box = useRef<HTMLDivElement>(null);
  /** A drag that starts in the panel and ends on the backdrop still clicks the backdrop. */
  const pressedBackdrop = useRef(false);

  useEffect(() => {
    const origin = opener.current;
    (box.current?.querySelector<HTMLElement>("[data-autofocus]") ?? box.current)?.focus();
    return () => {
      // On small screens the opener can be inside the drawer that has closed meanwhile;
      // the button that reopens the drawer is then the nearest sensible place.
      const target = origin && isShown(origin) ? origin : document.querySelector<HTMLElement>("main button");
      target?.focus();
    };
  }, [opener]);

  // When every control is disabled (a pending form) the focus would fall out to the page.
  useEffect(() => {
    if (!box.current?.contains(document.activeElement)) box.current?.focus();
  });

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      // The shell closes its drawer on Escape; this one belongs to the dialog.
      e.stopPropagation();
      if (dismissable) onDismiss();
      return;
    }
    if (e.key !== "Tab") return;
    const stops = [...(box.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    const edge = e.shiftKey ? stops[0] : stops[stops.length - 1];
    if (stops.length === 0 || document.activeElement === edge || document.activeElement === box.current) {
      e.preventDefault();
      (e.shiftKey ? stops[stops.length - 1] : stops[0])?.focus();
    }
  };

  return createPortal(
    <div
      data-testid={backdropTestId}
      onMouseDown={(e) => {
        pressedBackdrop.current = e.target === e.currentTarget;
      }}
      onClick={() => {
        if (pressedBackdrop.current && dismissable) onDismiss();
        pressedBackdrop.current = false;
      }}
      className="fixed inset-0 z-50 flex animate-bt-fade items-center justify-center overflow-auto bg-backdrop p-6 backdrop-blur-[6px] max-md:p-4"
    >
      <div
        ref={box}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
        className="m-auto w-[min(420px,100%)] animate-bt-modal rounded-bt bg-panel shadow-2"
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}

/** False when the element or an ancestor is `display: none`, as the closed drawer's contents are. */
function isShown(element: HTMLElement): boolean {
  for (let el: HTMLElement | null = element; el; el = el.parentElement) {
    if (getComputedStyle(el).display === "none") return false;
  }
  return element.isConnected;
}
