import { useMutation } from "@tanstack/react-query";
import { submitFeedback } from "../services/api";
import type { FeedbackRequest, FeedbackResult } from "../types/api";

export function useFeedback() {
  return useMutation<
    FeedbackResult,
    Error,
    { historyId: string; rating: FeedbackRequest["rating"] }
  >({
    mutationFn: ({ historyId, rating }) =>
      submitFeedback(historyId, { rating }),
  });
}
