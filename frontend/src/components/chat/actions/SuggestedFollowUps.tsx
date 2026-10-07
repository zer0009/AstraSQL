import { useState } from "react";
import { cn } from "../../../lib/utils";
import { Button } from "../../ui";

export interface SuggestedFollowUpsProps {
  questions: string[];
  onSelect: (question: string) => void;
  /** Override the section label (e.g. "Did you mean?"). */
  label?: string;
  /** Visual variant: clarify (required) vs default (optional follow-ups). */
  variant?: "default" | "clarify";
}

function isOtherOption(text: string): boolean {
  return text.trim().toLowerCase().startsWith("other");
}

export function SuggestedFollowUps({
  questions,
  onSelect,
  label = "Continue exploring",
  variant = "default",
}: SuggestedFollowUpsProps) {
  const [otherOpen, setOtherOpen] = useState(false);
  const [otherText, setOtherText] = useState("");

  if (questions.length === 0) return null;

  const isClarify = variant === "clarify";
  const choices = questions.filter((q) => !isOtherOption(q));
  const otherLabel =
    questions.find((q) => isOtherOption(q)) ?? "Other — I'll rephrase the question";

  const submitOther = () => {
    const text = otherText.trim();
    if (!text) return;
    onSelect(text);
    setOtherText("");
    setOtherOpen(false);
  };

  return (
    <div
      className={cn(
        "space-y-2 pt-1",
        isClarify && "rounded-lg border border-amber-200 bg-amber-50/60 p-3",
      )}
      role={isClarify ? "group" : undefined}
      aria-label={isClarify ? "Clarification options" : undefined}
    >
      <p
        className={cn(
          "text-xs font-medium",
          isClarify ? "text-amber-900" : "text-zinc-500",
        )}
      >
        {label}
      </p>
      <div className="flex flex-wrap gap-2">
        {choices.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onSelect(q)}
            className={cn(
              "rounded-lg border px-3 py-1.5 text-left text-xs transition-colors",
              isClarify
                ? "border-amber-300 bg-white text-amber-950 hover:border-amber-400 hover:bg-amber-50"
                : "border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50",
            )}
          >
            {q}
          </button>
        ))}
        {isClarify || questions.some(isOtherOption) ? (
          <button
            key="__other__"
            type="button"
            onClick={() => setOtherOpen((v) => !v)}
            aria-expanded={otherOpen}
            className={cn(
              "rounded-lg border px-3 py-1.5 text-left text-xs transition-colors",
              isClarify
                ? "border-amber-300 bg-white text-amber-950 hover:border-amber-400 hover:bg-amber-50"
                : "border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50",
              otherOpen && "border-amber-400 bg-amber-50",
            )}
          >
            {otherLabel}
          </button>
        ) : null}
      </div>
      {otherOpen ? (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <input
            type="text"
            value={otherText}
            onChange={(e) => setOtherText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                submitOther();
              }
            }}
            placeholder="Describe what you mean…"
            className="w-full rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs text-zinc-800 outline-none ring-amber-200 focus:ring-2"
            autoFocus
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!otherText.trim()}
            onClick={submitOther}
          >
            Send
          </Button>
        </div>
      ) : null}
    </div>
  );
}
