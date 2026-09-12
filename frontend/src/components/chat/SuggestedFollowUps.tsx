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
    <div className="space-y-2 pt-1">
      <p className="text-xs font-medium text-zinc-500">Continue exploring</p>
      <div className="flex flex-wrap gap-2">
        {questions.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onSelect(q)}
            className="rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-left text-xs text-zinc-700 transition-colors hover:border-zinc-300 hover:bg-zinc-50"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
