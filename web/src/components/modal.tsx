"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

/** Minimal accessible modal: backdrop, role=dialog, Escape to close (unless `blocking`), focus moved
 *  inside while open. `blocking` modals cannot be dismissed - used for the terms of use. */
export function Modal({
  open, onClose, title, blocking = false, className, children,
}: {
  open: boolean;
  onClose?: () => void;
  title: string;
  blocking?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !blocking) onClose?.();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [open, blocking, onClose]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 p-0 backdrop-blur-sm sm:items-center sm:p-4"
      onMouseDown={(e) => { if (e.target === e.currentTarget && !blocking) onClose?.(); }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={cn(
          "flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-t-2xl border bg-card shadow-2xl outline-none sm:max-w-lg sm:rounded-2xl",
          className,
        )}
      >
        {children}
      </div>
    </div>
  );
}
