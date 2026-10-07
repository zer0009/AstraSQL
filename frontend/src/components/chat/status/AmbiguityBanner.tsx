import { cn } from "../../../lib/utils";
import type { TrustStatusViewModel } from "./trustStatus";

export function AmbiguityBanner({
  banner,
}: {
  banner: NonNullable<TrustStatusViewModel["banner"]>;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2 text-sm",
        banner.tone === "warn"
          ? "border-amber-200 bg-amber-50 text-amber-900"
          : "border-[var(--border)] bg-[var(--surface-muted)] text-zinc-700",
      )}
      role={banner.tone === "warn" ? "status" : undefined}
    >
      <p className="font-medium">{banner.title}</p>
      {banner.body ? (
        <p className="mt-0.5 text-xs opacity-90">{banner.body}</p>
      ) : null}
      {banner.why ? (
        <p className="mt-1 text-[11px] text-zinc-500">Why: {banner.why}</p>
      ) : null}
    </div>
  );
}
