import { describe, expect, it, vi } from "vitest";
import { resolveTrustStatus } from "../components/chat/status/trustStatus";

describe("resolveTrustStatus", () => {
  it("maps certified with short label", () => {
    const status = resolveTrustStatus({ trustLevel: "certified" });
    expect(status.level).toBe("certified");
    expect(status.label).toBe("Certified");
    expect(status.badgeVariant).toBe("success");
  });

  it("derives taught from usedGolden when level missing", () => {
    const status = resolveTrustStatus({ usedGolden: true });
    expect(status.level).toBe("taught");
    expect(status.label).toBe("Taught");
    expect(status.usedGolden).toBe(true);
  });

  it("maps guessed", () => {
    const status = resolveTrustStatus({ trustLevel: "guessed" });
    expect(status.level).toBe("guessed");
    expect(status.label).toBe("Guessed");
  });

  it("maps clarifying from ambiguity and sets warn banner", () => {
    const status = resolveTrustStatus({
      ambiguity: {
        status: "ambiguous",
        should_clarify: true,
        decision_why: "Two revenue definitions",
      },
    });
    expect(status.level).toBe("clarifying");
    expect(status.isClarifying).toBe(true);
    expect(status.banner?.tone).toBe("warn");
    expect(status.banner?.why).toBe("Two revenue definitions");
    expect(status.bannerShowsWhy).toBe(true);
  });

  it("maps failed from error", () => {
    const status = resolveTrustStatus({ error: "boom" });
    expect(status.level).toBe("failed");
    expect(status.label).toBe("Failed");
  });

  it("assumed banner vs card: showAssumptionChange when follow-up provided", () => {
    const onFollowUp = vi.fn();
    const status = resolveTrustStatus({
      ambiguity: {
        status: "assumed",
        decision_why: "Picked net revenue",
        assumption: "Using net revenue",
      },
      assumption: "Using net revenue",
      onFollowUp,
    });
    expect(status.banner?.title).toMatch(/Assumed/i);
    expect(status.bannerShowsWhy).toBe(true);
    expect(status.showAssumptionChange).toBe(true);
    expect(status.assumption).toBe("Using net revenue");
  });

  it("marks non-sql statuses", () => {
    const status = resolveTrustStatus({
      ambiguity: { status: "not_a_data_question" },
    });
    expect(status.isNonSql).toBe(true);
  });
});
