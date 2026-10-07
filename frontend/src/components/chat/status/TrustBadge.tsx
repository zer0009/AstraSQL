import { Badge } from "../../ui";
import type { TrustStatusViewModel } from "./trustStatus";

export function TrustBadge({ status }: { status: TrustStatusViewModel }) {
  if (!status.level) return null;
  return (
    <Badge variant={status.badgeVariant} title={status.title}>
      {status.label}
    </Badge>
  );
}
