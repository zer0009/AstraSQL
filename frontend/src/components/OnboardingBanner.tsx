import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listConnections } from "../services/api";
import { Button } from "./ui";

/**
 * Lightweight first-run checklist shown when the user has few/no connections
 * or unscanned connections.
 */
export function OnboardingBanner() {
  const connectionsQuery = useQuery({
    queryKey: ["connections"],
    queryFn: listConnections,
  });
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem("astrasql.onboarding.dismissed") === "1";
    } catch {
      return false;
    }
  });

  const connections = connectionsQuery.data ?? [];
  const steps = useMemo(() => {
    const hasConnection = connections.length > 0;
    const scanned = connections.some((c) => Boolean(c.last_scanned_at));
    return [
      {
        id: "connect",
        label: "Add a database connection",
        done: hasConnection,
        to: "/connections",
      },
      {
        id: "scan",
        label: "Scan schema",
        done: scanned,
        to: "/connections",
      },
      {
        id: "ask",
        label: "Ask your first question",
        done: false,
        to: "/",
      },
    ];
  }, [connections]);

  if (dismissed || connectionsQuery.isLoading) return null;
  if (connections.length > 0 && connections.every((c) => c.last_scanned_at)) {
    return null;
  }

  return (
    <div className="border-b border-amber-200 bg-amber-50 px-4 py-3">
      <div className="mx-auto flex max-w-4xl flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-amber-950">Getting started</p>
          <ol className="mt-1 space-y-1 text-xs text-amber-900">
            {steps.map((step, i) => (
              <li key={step.id} className="flex items-center gap-2">
                <span
                  className={
                    step.done
                      ? "text-emerald-700"
                      : "font-medium text-amber-950"
                  }
                >
                  {step.done ? "✓" : `${i + 1}.`}
                </span>
                <Link to={step.to} className="underline-offset-2 hover:underline">
                  {step.label}
                </Link>
              </li>
            ))}
          </ol>
        </div>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => {
            setDismissed(true);
            try {
              localStorage.setItem("astrasql.onboarding.dismissed", "1");
            } catch {
              // ignore
            }
          }}
        >
          Dismiss
        </Button>
      </div>
    </div>
  );
}
