import { useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { Button } from "../ui";
import { useFeedback } from "../../hooks/useFeedback";

export interface FeedbackBarProps {
  historyId: string;
}

export function FeedbackBar({ historyId }: FeedbackBarProps) {
  const feedback = useFeedback();
  const [rating, setRating] = useState<1 | -1 | null>(null);
  const [goldenSaved, setGoldenSaved] = useState(false);

  const submit = (value: 1 | -1) => {
    if (feedback.isPending || rating !== null) return;
    feedback.mutate(
      { historyId, rating: value },
      {
        onSuccess: (result) => {
          setRating(value);
          if (value === 1 && result.golden_record_id) {
            setGoldenSaved(true);
            window.setTimeout(() => setGoldenSaved(false), 2500);
          } else if (value === 1) {
            setGoldenSaved(true);
            window.setTimeout(() => setGoldenSaved(false), 2500);
          }
        },
      },
    );
  };

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-zinc-100 pt-2">
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
        onClick={() => submit(-1)}
        aria-label="Thumbs down"
      >
        <ThumbsDown className="h-3.5 w-3.5" strokeWidth={1.75} />
      </Button>
      {goldenSaved ? (
        <span className="text-xs text-emerald-700">Saved as golden record</span>
      ) : null}
      {feedback.isError ? (
        <span className="text-xs text-red-600">Could not save feedback</span>
      ) : null}
    </div>
  );
}
