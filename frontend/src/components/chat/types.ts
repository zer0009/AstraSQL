import type { TrustLevel } from "./status/trustStatus";

export type { TrustLevel };

export type AgentMessageActions = {
  onFollowUp?: (question: string) => void;
  onRefine?: (runId: string, choice: string) => void;
  onRemember?: (definition: string) => void;
  onAskAgain?: () => void;
  onRerunSql?: (sql?: string) => void;
  onRetry?: () => void;
};
