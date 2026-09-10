export interface SuggestedFollowUpsProps {
  questions: string[];
  onSelect: (question: string) => void;
}

export function SuggestedFollowUps({
  questions,
  onSelect,
}: SuggestedFollowUpsProps) {
  if (questions.length === 0) return null;

  return (
    <div className="space-y-1.5 border-t border-zinc-100 pt-2">
      <p className="text-xs font-medium text-zinc-500">Suggested follow-ups</p>
      <div className="flex flex-wrap gap-1.5">
        {questions.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onSelect(q)}
            className="rounded-md border border-zinc-200 bg-white px-2.5 py-1 text-left text-xs text-zinc-700 transition-colors hover:border-zinc-300 hover:bg-zinc-50"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
