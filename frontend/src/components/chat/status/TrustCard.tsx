import { Button } from "../../ui";

export function TrustCard({
  assumption,
  keyFinding,
  decisionWhy,
  onChangeAssumption,
  onRemember,
}: {
  assumption?: string;
  keyFinding?: string;
  /** Only pass when AmbiguityBanner is not already showing why. */
  decisionWhy?: string;
  onChangeAssumption?: () => void;
  onRemember?: () => void;
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
          <div className="mt-2 flex flex-wrap gap-2">
            {onChangeAssumption ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={onChangeAssumption}
              >
                Change assumption
              </Button>
            ) : null}
            {onRemember ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={onRemember}
              >
                Remember this definition
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
