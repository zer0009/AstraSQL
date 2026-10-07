import { Badge } from "../../ui";
import { formatConfidence } from "../../../lib/confidence";
import { cn } from "../../../lib/utils";

export function ConfidenceBadge({
  value,
  className,
}: {
  value: string | number | null | undefined;
  className?: string;
}) {
  const level = formatConfidence(value);
  if (!level) {
    return <span className="text-xs text-[var(--text-muted)]">—</span>;
  }

  return (
    <Badge
      className={cn(
        level === "HIGH" && "border-zinc-300 bg-zinc-100 text-zinc-800",
        level === "MEDIUM" && "border-amber-200 bg-amber-50 text-amber-800",
        level === "LOW" && "border-red-200 bg-red-50 text-red-700",
        className,
      )}
    >
      {level}
    </Badge>
  );
}
