import { useMemo, useState } from "react";
import type { QueryResult } from "../../../types/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../ui";
import { ResultChart } from "../../chart/ResultChart";
import { detectChartShape } from "../../chart/detectChartShape";
import { ResultsTable } from "./ResultsTable";

export interface ResultTabsProps {
  results: QueryResult;
}

export function ResultTabs({ results }: ResultTabsProps) {
  const shapeInfo = useMemo(() => detectChartShape(results), [results]);
  const hasChart = shapeInfo.shape !== "none";
  const [tab, setTab] = useState(hasChart ? "chart" : "table");
  const activeTab = hasChart ? tab : "table";

  if (!hasChart) {
    return <ResultsTable results={results} />;
  }

  return (
    <Tabs value={activeTab} onValueChange={setTab} defaultValue="chart">
      <TabsList>
        <TabsTrigger value="chart">Chart</TabsTrigger>
        <TabsTrigger value="table">Table</TabsTrigger>
      </TabsList>
      <TabsContent value="chart" className="mt-2">
        <ResultChart results={results} shapeInfo={shapeInfo} />
      </TabsContent>
      <TabsContent value="table" className="mt-2">
        <ResultsTable results={results} />
      </TabsContent>
    </Tabs>
  );
}
