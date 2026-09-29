import { useMutation } from "@tanstack/react-query";
import { submitFeedback } from "../services/api";
import type { FeedbackRequest, FeedbackResult } from "../types/api";

export function useFeedback() {
  return useMutation<
    FeedbackResult,
    Error,
    {
      historyId: string;
      rating: FeedbackRequest["rating"];
      corrected_sql?: string;
      new_rule?: string;
    }
  >({
    mutationFn: ({ historyId, rating, corrected_sql, new_rule }) =>
      submitFeedback(historyId, {
        rating,
        ...(corrected_sql ? { corrected_sql } : {}),
        ...(new_rule ? { new_rule } : {}),
      }),
  });
}
