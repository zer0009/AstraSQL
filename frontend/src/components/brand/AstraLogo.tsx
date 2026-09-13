import { cn } from "../../lib/utils";

export interface AstraLogoProps {
  /** Icon-only vs icon + wordmark */
  variant?: "mark" | "full";
  /** Pixel size of the mark square */
  size?: number;
  className?: string;
  /** Hide wordmark text (same as variant="mark") */
  markOnly?: boolean;
}

/**
 * AstraSQL brand mark: zinc rounded square + star/table glyph + teal accent.
 * Star (Astra) + data grid (SQL) on zinc-900, matching the app chrome.
 */
export function AstraLogo({
  variant = "full",
  size = 28,
  className,
  markOnly = false,
}: AstraLogoProps) {
  const showWordmark = variant === "full" && !markOnly;

  return (
    <span
      className={cn("inline-flex items-center gap-2", className)}
      aria-label="AstraSQL"
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 64 64"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="shrink-0"
        aria-hidden
      >
        <rect width="64" height="64" rx="14" fill="#18181B" />
        <path fill="#FAFAFA" d="M32 10 L38 26 H26 Z" />
        <path fill="#FAFAFA" d="M32 54 L26 38 H38 Z" />
        <rect x="18" y="26" width="28" height="12" rx="1.5" fill="#FAFAFA" />
        <rect x="26.5" y="27.5" width="1.5" height="9" fill="#18181B" />
        <rect x="36" y="27.5" width="1.5" height="9" fill="#18181B" />
        <rect x="15" y="31" width="34" height="2" rx="1" fill="#0D9488" />
      </svg>
      {showWordmark ? (
        <span className="text-sm font-semibold tracking-tight text-zinc-900">
          AstraSQL
        </span>
      ) : null}
    </span>
  );
}
