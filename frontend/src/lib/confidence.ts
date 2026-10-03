/** Confidence thresholds shared with backend History stats (0.85 high). */
export const CONFIDENCE_HIGH = 0.85;
export const CONFIDENCE_MEDIUM = 0.4;

export type ConfidenceLabel = "HIGH" | "MEDIUM" | "LOW";

export function formatConfidence(
  value: string | number | undefined | null,
): ConfidenceLabel | null {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value === "number") {
    if (value >= CONFIDENCE_HIGH) return "HIGH";
    if (value >= CONFIDENCE_MEDIUM) return "MEDIUM";
    return "LOW";
  }
  const upper = String(value).toUpperCase();
  if (upper === "HIGH" || upper === "MEDIUM" || upper === "LOW") {
    return upper;
  }
  return upper as ConfidenceLabel;
}
