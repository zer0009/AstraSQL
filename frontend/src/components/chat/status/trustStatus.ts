import { statusCopy } from "../../../lib/ambiguity";
import type { Ambiguity, AmbiguityStatus } from "../../../types/api";

export type TrustLevel =
  | "certified"
  | "taught"
  | "guessed"
  | "clarifying"
  | "failed";

export type BadgeVariant =
  | "success"
  | "warning"
  | "secondary"
  | "outline"
  | "danger";

export type TrustStatusViewModel = {
  level: TrustLevel | null;
  label: string;
  title: string;
  badgeVariant: BadgeVariant;
  banner: {
    title: string;
    body?: string;
    why?: string;
    tone: "warn" | "neutral";
  } | null;
  keyFinding?: string;
  assumption?: string;
  /** True when banner already shows decision_why — TrustCard must not repeat it. */
  bannerShowsWhy: boolean;
  showAssumptionChange: boolean;
  usedGolden: boolean;
  isClarifying: boolean;
  isNonSql: boolean;
};

const LABELS: Record<TrustLevel, string> = {
  certified: "Certified",
  taught: "Taught",
  guessed: "Guessed",
  clarifying: "Clarifying",
  failed: "Failed",
};

const TITLES: Record<TrustLevel, string> = {
  certified: "Generated SQL matches a saved answer for this project",
  taught: "A saved example was retrieved, but this SQL is not an exact match",
  guessed: "No saved answer was used; this is a cold guess",
  clarifying: "Asked for a definition instead of guessing",
  failed: "The query did not complete",
};

const VARIANTS: Record<TrustLevel, BadgeVariant> = {
  certified: "success",
  taught: "warning",
  guessed: "secondary",
  clarifying: "outline",
  failed: "danger",
};

export function trustLabel(level: TrustLevel): string {
  return LABELS[level];
}

export function trustTitle(level: TrustLevel): string {
  return TITLES[level];
}

export function trustBadgeVariant(level: TrustLevel): BadgeVariant {
  return VARIANTS[level];
}

export function asTrustLevel(value: string | undefined): TrustLevel | null {
  if (!value) return null;
  const key = value.toLowerCase() as TrustLevel;
  return key in LABELS ? key : null;
}

export type TrustStatusInput = {
  trustLevel?: string;
  usedGolden?: boolean;
  ambiguity?: Ambiguity;
  assumption?: string;
  keyFinding?: string;
  error?: string;
  onFollowUp?: (question: string) => void;
};

/**
 * Single mapper from stream/message fields → UI trust view-model.
 * Components must not re-derive taught/golden/clarifying in JSX.
 */
export function resolveTrustStatus(input: TrustStatusInput): TrustStatusViewModel {
  const ambiguityStatus = input.ambiguity?.status as AmbiguityStatus | undefined;
  const usedGolden = Boolean(input.usedGolden);
  const isClarifying =
    input.trustLevel === "clarifying" ||
    Boolean(input.ambiguity?.should_clarify) ||
    ambiguityStatus === "ambiguous";
  const isNonSql =
    ambiguityStatus === "not_a_data_question" ||
    ambiguityStatus === "unanswerable";

  let level = asTrustLevel(input.trustLevel);
  if (!level && input.error) level = "failed";
  if (!level && usedGolden) level = "taught";
  if (!level && ambiguityStatus === "ambiguous") level = "clarifying";

  const copy = statusCopy(ambiguityStatus);
  const why = input.ambiguity?.decision_why;
  const showBanner = Boolean(copy && ambiguityStatus && ambiguityStatus !== "clear");
  const bannerShowsWhy = Boolean(showBanner && why);

  const banner = showBanner && copy
    ? {
        title: copy.title,
        body: copy.body,
        why: why || undefined,
        tone: (isClarifying ? "warn" : "neutral") as "warn" | "neutral",
      }
    : null;

  const assumption = input.assumption ?? input.ambiguity?.assumption;
  const showAssumptionChange =
    ambiguityStatus === "assumed" && Boolean(input.onFollowUp);

  return {
    level,
    label: level ? LABELS[level] : "",
    title: level ? TITLES[level] : "",
    badgeVariant: level ? VARIANTS[level] : "secondary",
    banner,
    keyFinding: input.keyFinding,
    assumption,
    bannerShowsWhy,
    showAssumptionChange,
    usedGolden,
    isClarifying,
    isNonSql,
  };
}
