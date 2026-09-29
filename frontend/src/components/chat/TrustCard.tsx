import { Badge } from "../ui";

export type TrustLevel =
  | "certified"
  | "taught"
  | "guessed"
  | "clarifying"
  | "failed";

const LABELS: Record<TrustLevel, string> = {
  certified: "Certified",
  taught: "Taught",
  guessed: "Guessed",
  clarifying: "Clarifying",
  failed: "Failed",
};

const VARIANTS: Record<
  TrustLevel,
  "success" | "warning" | "secondary" | "outline" | "danger"
> = {
  certified: "success",
  taught: "warning",
  guessed: "secondary",
  clarifying: "outline",
  failed: "danger",
};

const TITLES: Record<TrustLevel, string> = {
  certified: "Generated SQL matches a golden record for this project",
  taught: "A golden example was retrieved, but this SQL is not an exact match",
  guessed: "No golden record was used; this is a cold guess",
  clarifying: "Asked for a definition instead of guessing",
  failed: "The query did not complete",
};

function asTrustLevel(value: string | undefined): TrustLevel | null {
  if (!value) return null;
  const key = value.toLowerCase() as TrustLevel;
  return key in LABELS ? key : null;
}

export function TrustBadge({ level }: { level?: string }) {
  const trust = asTrustLevel(level);
  if (!trust) return null;
  return (
    <Badge variant={VARIANTS[trust]} title={TITLES[trust]}>
      {LABELS[trust]}
    </Badge>
  );
}

export function TrustCard({
  assumption,
  keyFinding,
}: {
  assumption?: string;
  keyFinding?: string;
}) {
  if (!assumption && !keyFinding) return null;
  return (
    <div className="space-y-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-2">
      {keyFinding ? (
        <p className="text-sm text-zinc-800">
          <span className="text-[11px] font-medium uppercase tracking-wide text-zinc-400">
            Key finding
          </span>
          <span className="mt-0.5 block">{keyFinding}</span>
        </p>
      ) : null}
      {assumption ? (
        <p className="text-sm text-zinc-700">
          <span className="text-[11px] font-medium uppercase tracking-wide text-zinc-400">
            Assumption
          </span>
          <span className="mt-0.5 block">{assumption}</span>
        </p>
      ) : null}
    </div>
  );
}
