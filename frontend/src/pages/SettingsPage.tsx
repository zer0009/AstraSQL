import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "../components/PageHeader";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Select,
  Spinner,
} from "../components/ui";
import { getPublicSettings } from "../services/api";

const DENSITY_KEY = "astrasql.ui.density";

type Density = "comfortable" | "compact";

function readDensity(): Density {
  const raw = localStorage.getItem(DENSITY_KEY);
  return raw === "compact" ? "compact" : "comfortable";
}

function applyDensity(density: Density) {
  document.documentElement.dataset.density = density;
  localStorage.setItem(DENSITY_KEY, density);
}

function SettingRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-0.5 border-b border-zinc-100 py-3 last:border-0 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <dt className="text-xs font-medium text-zinc-500">{label}</dt>
      <dd className="text-sm text-zinc-900 sm:text-right">{children}</dd>
    </div>
  );
}

export default function SettingsPage() {
  const [density, setDensity] = useState<Density>(() => readDensity());

  const settingsQuery = useQuery({
    queryKey: ["settings", "public"],
    queryFn: getPublicSettings,
  });

  useEffect(() => {
    applyDensity(density);
  }, [density]);

  const settings = settingsQuery.data;

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Settings"
        description="Application configuration"
      />
      <div className="flex-1 space-y-4 overflow-auto p-5">
        <Card>
          <CardHeader>
            <CardTitle>Server configuration</CardTitle>
            <CardDescription>
              Read-only values from{" "}
              <code className="rounded bg-zinc-100 px-1 py-0.5 text-[11px]">
                GET /api/settings/public
              </code>
            </CardDescription>
          </CardHeader>
          <CardContent>
            {settingsQuery.isLoading ? (
              <div className="flex items-center gap-2 py-6 text-sm text-zinc-500">
                <Spinner size="sm" />
                Loading settings…
              </div>
            ) : settingsQuery.isError ? (
              <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                Failed to load public settings.
              </p>
            ) : settings ? (
              <dl>
                {settings.app_name ? (
                  <SettingRow label="App name">{settings.app_name}</SettingRow>
                ) : null}
                <SettingRow label="LLM provider">
                  <span className="font-medium">{settings.llm_provider}</span>
                </SettingRow>
                <SettingRow label="Model">
                  <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs">
                    {settings.openai_model}
                  </code>
                </SettingRow>
                <SettingRow label="Max result rows">
                  {settings.max_result_rows}
                </SettingRow>
                <SettingRow label="Available database types">
                  <div className="flex flex-wrap justify-end gap-1">
                    {settings.database_types.length === 0 ? (
                      <span className="text-zinc-400">None registered</span>
                    ) : (
                      settings.database_types.map((t) => (
                        <Badge key={t} variant="secondary">
                          {t}
                        </Badge>
                      ))
                    )}
                  </div>
                </SettingRow>
              </dl>
            ) : null}

            <p className="mt-4 rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs text-zinc-600">
              Configure via environment variables (
              <code className="rounded bg-white px-1 py-0.5">.env</code>) on
              the server.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Local preferences</CardTitle>
            <CardDescription>
              Stored in this browser only (
              <code className="rounded bg-zinc-100 px-1 py-0.5 text-[11px]">
                localStorage
              </code>
              )
            </CardDescription>
          </CardHeader>
          <CardContent>
            <label className="flex max-w-xs flex-col gap-1">
              <span className="text-xs font-medium text-zinc-500">
                Theme density
              </span>
              <Select
                value={density}
                onChange={(e) => setDensity(e.target.value as Density)}
              >
                <option value="comfortable">Comfortable</option>
                <option value="compact">Compact</option>
              </Select>
            </label>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
