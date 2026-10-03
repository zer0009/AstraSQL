import { Badge, Button } from "../ui";
import type { AmbiguityStatus } from "../../types/api";

export type TrustLevel =
  | "certified"
  | "taught"
  | "guessed"
  | "clarifying"
  | "failed";

const LABELS: Record<TrustLevel, string> = {
  certified: "Verified answer",
  taught: "Learned from your team",
  guessed: "Best guess",
  clarifying: "Needs clarification",
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
  certified: "Generated SQL matches a saved answer for this project",
  taught: "A saved example was retrieved, but this SQL is not an exact match",
  guessed: "No saved answer was used; this is a cold guess",
  clarifying: "Asked for a definition instead of guessing",
  failed: "The query did not complete",
};

function asTrustLevel(value: string | undefined): TrustLevel | null {
  if (!value) return null;
  const key = value.toLowerCase() as TrustLevel;
  return key in LABELS ? key : null;
}

export function TrustBadge({
  level,
  usedGolden,
  ambiguityStatus,
}: {
  level?: string;
  usedGolden?: boolean;
  ambiguityStatus?: AmbiguityStatus;
}) {
  let trust = asTrustLevel(level);
  if (!trust && usedGolden) trust = "taught";
  if (!trust && ambiguityStatus === "ambiguous") trust = "clarifying";
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
  decisionWhy,
  usedGolden,
  onChangeAssumption,
}: {
  assumption?: string;
  keyFinding?: string;
  decisionWhy?: string;
  usedGolden?: boolean;
  onChangeAssumption?: () => void;
}) {
  if (!assumption && !keyFinding && !usedGolden) return null;
  return (
    <div className="space-y-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-2">
      {usedGolden ? (
        <p className="text-xs text-amber-800">
          Matched a saved example for this connection.
        </p>
      ) : null}
      {keyFinding ? (
        <p className="text-sm text-zinc-800">
          <span className="text-[11px] font-medium uppercase tracking-wide text-zinc-400">
            Key finding
          </span>
          <span className="mt-0.5 block">{keyFinding}</span>
        </p>
      ) : null}
      {assumption ? (
        <div className="text-sm text-zinc-700">
          <span className="text-[11px] font-medium uppercase tracking-wide text-zinc-400">
            Assumption
          </span>
          <span className="mt-0.5 block">{assumption}</span>
          {decisionWhy ? (
            <span className="mt-0.5 block text-[11px] text-zinc-400">
              {decisionWhy}
            </span>
          ) : null}
          {onChangeAssumption ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="mt-2"
              onClick={onChangeAssumption}
            >
              Change assumption
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
