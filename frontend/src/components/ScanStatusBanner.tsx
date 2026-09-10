import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Link } from "react-router-dom";
import { listScanJobs } from "../services/api";
import type { ScanJobStatus } from "../types/api";

function isActive(job: ScanJobStatus): boolean {
  return job.status === "pending" || job.status === "running";
}

/** Global banner so scan progress is visible on every page. */
export function ScanStatusBanner() {
  const scansQuery = useQuery({
    queryKey: ["connection-scans"],
    queryFn: () => listScanJobs(false),
    refetchInterval: (query) => {
      const jobs = query.state.data ?? [];
      return jobs.some(isActive) ? 1000 : false;
    },
  });

  const active = (scansQuery.data ?? []).filter(isActive);
  if (active.length === 0) return null;

  return (
    <div className="shrink-0 border-b border-amber-200 bg-amber-50 px-4 py-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-amber-900">
        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" strokeWidth={2} />
        {active.map((job) => (
          <div key={job.job_id} className="min-w-0">
            <span className="font-medium">{job.connection_name}</span>
            <span className="text-amber-800">
              {" "}
              — {job.percent}% · {job.message}
              {job.current_table ? (
                <>
                  {" "}
                  (<span className="font-mono">{job.current_table}</span>)
                </>
              ) : null}
              {job.tables_total > 0
                ? ` · ${job.tables_done}/${job.tables_total} tables`
                : null}
            </span>
          </div>
        ))}
        <Link
          to="/connections"
          className="ml-auto font-medium text-amber-950 underline-offset-2 hover:underline"
        >
          View details
        </Link>
      </div>
    </div>
  );
}
