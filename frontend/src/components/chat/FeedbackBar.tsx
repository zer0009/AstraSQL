import { useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { Button, Textarea } from "../ui";
import { useFeedback } from "../../hooks/useFeedback";

export interface FeedbackBarProps {
  historyId: string;
  /** Original SQL — enables in-chat correction on thumbs down. */
  sql?: string;
}

export function FeedbackBar({ historyId, sql }: FeedbackBarProps) {
  const feedback = useFeedback();
  const [rating, setRating] = useState<1 | -1 | null>(null);
  const [goldenSaved, setGoldenSaved] = useState(false);
  const [showCorrection, setShowCorrection] = useState(false);
  const [correctionDraft, setCorrectionDraft] = useState(sql ?? "");

  const flashGolden = () => {
    setGoldenSaved(true);
    window.setTimeout(() => setGoldenSaved(false), 2500);
  };

  const submit = (value: 1 | -1, correctedSql?: string) => {
    if (feedback.isPending || rating !== null) return;
    feedback.mutate(
      {
        historyId,
        rating: value,
        corrected_sql: correctedSql,
      },
      {
        onSuccess: (result) => {
          setRating(value);
          setShowCorrection(false);
          if (result.golden_record_id || value === 1) {
            flashGolden();
          }
        },
      },
    );
  };

  const onThumbsDown = () => {
    if (feedback.isPending || rating !== null) return;
    if (sql) {
      setCorrectionDraft(sql);
      setShowCorrection(true);
      return;
    }
    submit(-1);
  };

  const saveCorrection = () => {
    const trimmed = correctionDraft.trim();
    if (!trimmed) return;
    submit(-1, trimmed);
  };

  return (
    <div className="space-y-2 border-t border-zinc-100 pt-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-zinc-500">Was this helpful?</span>
        <Button
          type="button"
          variant={rating === 1 ? "secondary" : "ghost"}
          size="sm"
          disabled={feedback.isPending || rating !== null}
          onClick={() => submit(1)}
          aria-label="Thumbs up"
        >
          <ThumbsUp className="h-3.5 w-3.5" strokeWidth={1.75} />
        </Button>
        <Button
          type="button"
          variant={rating === -1 ? "secondary" : "ghost"}
          size="sm"
          disabled={feedback.isPending || rating !== null}
          onClick={onThumbsDown}
          aria-label="Thumbs down"
        >
          <ThumbsDown className="h-3.5 w-3.5" strokeWidth={1.75} />
        </Button>
        {goldenSaved ? (
          <span className="text-xs text-emerald-700">
            {rating === -1
              ? "Correction saved as golden record"
              : "Saved as golden record"}
          </span>
        ) : null}
        {feedback.isError ? (
          <span className="text-xs text-red-600">Could not save feedback</span>
        ) : null}
      </div>

      {showCorrection && rating === null ? (
        <div className="space-y-2 rounded-md border border-zinc-200 bg-zinc-50 p-2.5">
          <p className="text-xs text-zinc-600">
            Paste or edit the correct SQL. Saving stores it as a golden record
            for future queries.
          </p>
          <Textarea
            value={correctionDraft}
            onChange={(e) => setCorrectionDraft(e.target.value)}
            className="max-h-48 min-h-[6rem] resize-y font-mono text-xs"
            spellCheck={false}
            aria-label="Corrected SQL"
          />
          <div className="flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={feedback.isPending}
              onClick={() => setShowCorrection(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={feedback.isPending || !correctionDraft.trim()}
              onClick={saveCorrection}
            >
              Save correction
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
