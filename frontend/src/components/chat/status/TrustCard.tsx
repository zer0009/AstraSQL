import { Button } from "../../ui";

export function TrustCard({
  assumption,
  keyFinding,
  decisionWhy,
  onChangeAssumption,
}: {
  assumption?: string;
  keyFinding?: string;
  /** Only pass when AmbiguityBanner is not already showing why. */
  decisionWhy?: string;
  onChangeAssumption?: () => void;
}) {
  if (!assumption && !keyFinding) return null;

  return (
    <div className="space-y-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] px-3 py-2">
      {keyFinding ? (
        <p className="text-sm text-[var(--text)]">
          <span className="text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
            Key finding
          </span>
          <span className="mt-0.5 block">{keyFinding}</span>
        </p>
      ) : null}
      {assumption ? (
        <div className="text-sm text-[var(--text)]">
          <span className="text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
            Assumption
          </span>
          <span className="mt-0.5 block text-zinc-700">{assumption}</span>
          {decisionWhy ? (
            <span className="mt-0.5 block text-[11px] text-[var(--text-muted)]">
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
