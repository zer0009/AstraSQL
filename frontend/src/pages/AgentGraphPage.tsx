import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "../components/PageHeader";
import { Badge, Card, CardContent, CardHeader, CardTitle, Spinner } from "../components/ui";
import { getAgentGraph } from "../services/api";

export default function AgentGraphPage() {
  const graphQuery = useQuery({
    queryKey: ["agent-graph"],
    queryFn: getAgentGraph,
  });

  const data = graphQuery.data;

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Agent graph"
        description="How AstraSQL routes a question from retrieval through SQL generation, the consistency gate, validation, and execution."
      />
      <div className="flex-1 space-y-4 overflow-auto p-5">
        {graphQuery.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <Spinner size="sm" /> Loading graph…
          </div>
        ) : graphQuery.isError ? (
          <p className="text-sm text-red-600">Could not load agent graph.</p>
        ) : data ? (
          <>
            <div className="flex flex-wrap gap-2">
              <Badge variant="secondary">
                merge interpret+generate:{" "}
                {data.merge_interpret_generate ? "on" : "off"}
              </Badge>
              <Badge variant="secondary">
                execution evidence gate:{" "}
                {data.execution_evidence_gate ? "on" : "off"}
              </Badge>
              <Badge variant="outline">{data.nodes.length} nodes</Badge>
            </div>
            <Card>
              <CardHeader>
                <CardTitle>Mermaid</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="overflow-auto rounded-md border border-zinc-200 bg-zinc-50 p-3 text-xs text-zinc-800">
                  {data.mermaid}
                </pre>
                <p className="mt-2 text-xs text-zinc-500">
                  Paste into a Mermaid live editor to visualize. Chat already
                  streams the visited steps for each answer.
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Nodes</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="flex flex-wrap gap-1.5">
                  {data.nodes.map((n) => (
                    <Badge key={n} variant="outline">
                      {n}
                    </Badge>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </>
        ) : null}
      </div>
    </div>
  );
}
