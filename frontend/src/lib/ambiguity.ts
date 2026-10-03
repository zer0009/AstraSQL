import type { Ambiguity, AmbiguityStatus } from "../types/api";

export function parseAmbiguity(value: unknown): Ambiguity | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const obj = value as Record<string, unknown>;
  const statusRaw = typeof obj.status === "string" ? obj.status.toLowerCase() : "";
  const status = (statusRaw || undefined) as AmbiguityStatus | undefined;

  const options = Array.isArray(obj.options)
    ? obj.options.map(String).filter(Boolean)
    : undefined;

  const decisionPoints = Array.isArray(obj.decision_points)
    ? obj.decision_points
        .map((item) => {
          if (!item || typeof item !== "object") return null;
          const dp = item as Record<string, unknown>;
          return {
            key: typeof dp.key === "string" ? dp.key : String(dp.key ?? ""),
            question:
              typeof dp.question === "string"
                ? dp.question
                : typeof dp.prompt === "string"
                  ? dp.prompt
                  : undefined,
            options: Array.isArray(dp.options)
              ? dp.options.map(String)
              : undefined,
          };
        })
        .filter((d): d is NonNullable<typeof d> => d !== null && Boolean(d.key))
    : undefined;

  return {
    status,
    should_clarify: Boolean(obj.should_clarify),
    reason: typeof obj.reason === "string" ? obj.reason : undefined,
    options,
    decision_why:
      typeof obj.decision_why === "string" ? obj.decision_why : undefined,
    assumption:
      typeof obj.assumption === "string" ? obj.assumption : undefined,
    decision_points: decisionPoints,
    needs_execution_gate: Boolean(obj.needs_execution_gate),
    gate: obj.gate && typeof obj.gate === "object"
      ? (obj.gate as Record<string, unknown>)
      : undefined,
    clusters: Array.isArray(obj.clusters) ? obj.clusters : undefined,
  };
}

export function parseAmbiguityJson(
  raw: string | null | undefined,
): Ambiguity | undefined {
  if (!raw) return undefined;
  try {
    return parseAmbiguity(JSON.parse(raw));
  } catch {
    return undefined;
  }
}

export function clarificationOptionsFrom(
  topLevel: string[] | undefined,
  ambiguity: Ambiguity | undefined,
): string[] | undefined {
  if (topLevel && topLevel.length > 0) return topLevel;
  if (ambiguity?.options && ambiguity.options.length > 0) {
    return ambiguity.options;
  }
  return undefined;
}

export function statusCopy(status: AmbiguityStatus | undefined): {
  title: string;
  body?: string;
} | null {
  switch (status) {
    case "assumed":
      return {
        title: "Assumed an interpretation",
        body: "The question had more than one reading; we picked the most likely one.",
      };
    case "ambiguous":
      return {
        title: "Clarification needed",
        body: "Different interpretations would return different answers.",
      };
    case "unanswerable":
      return {
        title: "Cannot answer from this data",
        body: "The schema does not appear to contain what this question asks for.",
      };
    case "not_a_data_question":
      return {
        title: "Not a data question",
        body: "This looks like a general question rather than a request for data.",
      };
    case "failed_open":
      return {
        title: "Proceeded without a consistency check",
      };
    default:
      return null;
  }
}
