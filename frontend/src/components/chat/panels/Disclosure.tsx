import type { ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "../../../lib/utils";

export function Disclosure({
  title,
  open,
  onOpenChange,
  summary,
  trailing,
  children,
  className,
}: {
  title: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  summary?: ReactNode;
  trailing?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface-muted)]/60",
        className,
      )}
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-xs font-medium text-zinc-600 hover:bg-zinc-100/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-inset"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
        )}
        <span>{title}</span>
        {!open && summary ? (
          <span className="ml-1 font-normal text-[var(--text-muted)]">
            {summary}
          </span>
        ) : null}
        {trailing ? <span className="ml-auto">{trailing}</span> : null}
      </button>
      {open ? (
        <div className="space-y-2 border-t border-[var(--border)] bg-[var(--surface-raised)] p-2.5">
          {children}
        </div>
      ) : null}
    </div>
  );
}
