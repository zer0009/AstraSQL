import { useMemo, useState } from "react";
import type { QueryResult } from "../../types/api";
import { cn } from "../../lib/utils";
import { ResultsTable } from "./ResultsTable";
import { ResultChart } from "../chart/ResultChart";
import { detectChartShape } from "../chart/detectChartShape";

export interface ResultTabsProps {
  results: QueryResult;
}

type Tab = "chart" | "table";

export function ResultTabs({ results }: ResultTabsProps) {
  const shapeInfo = useMemo(() => detectChartShape(results), [results]);
  const hasChart = shapeInfo.shape !== "none";
  const [tab, setTab] = useState<Tab>(hasChart ? "chart" : "table");

  // When shape collapses to none (e.g. after re-run with different shape), stay on table
  const activeTab: Tab = hasChart ? tab : "table";

  if (!hasChart) {
    return <ResultsTable results={results} />;
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1 border-b border-zinc-200">
        {(["chart", "table"] as const).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={cn(
              "px-3 py-1.5 text-xs font-medium capitalize transition-colors",
              activeTab === key
                ? "border-b-2 border-zinc-900 text-zinc-900"
                : "text-zinc-500 hover:text-zinc-800",
            )}
          >
            {key}
          </button>
        ))}
      </div>
      {activeTab === "chart" ? (
        <ResultChart results={results} shapeInfo={shapeInfo} />
      ) : (
        <ResultsTable results={results} />
      )}
    </div>
  );
}
