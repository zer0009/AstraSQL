import { useEffect, useState, type FormEvent } from "react";
import { isAxiosError } from "axios";
import {
  createConnection,
  testConnection,
  updateConnection,
} from "../../services/api";
import type { Connection, ConnectionCreate } from "../../types/api";
import { Button, Input, Select, Spinner } from "../ui";

const DEFAULT_PORTS: Record<string, number> = {
  postgresql: 5432,
  mysql: 3306,
  mssql: 1433,
};

const DB_TYPE_OPTIONS = [
  { value: "postgresql", label: "PostgreSQL", disabled: false },
  { value: "mysql", label: "MySQL (coming soon)", disabled: true },
  { value: "mssql", label: "MSSQL (coming soon)", disabled: true },
] as const;

function getErrorMessage(err: unknown, fallback: string): string {
  if (isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d: { msg?: string }) => d.msg ?? String(d))
        .join("; ");
    }
    return err.message || fallback;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}

export interface ConnectionFormProps {
  connection?: Connection | null;
  onSuccess: (connection: Connection) => void;
  onCancel: () => void;
}

interface FormState {
  name: string;
  db_type: string;
  host: string;
  port: string;
  database: string;
  username: string;
  password: string;
  ssl_enabled: boolean;
}

function toFormState(connection?: Connection | null): FormState {
  if (!connection) {
    return {
      name: "",
      db_type: "postgresql",
      host: "localhost",
      port: String(DEFAULT_PORTS.postgresql),
      database: "",
      username: "",
      password: "",
      ssl_enabled: false,
    };
  }
  return {
    name: connection.name,
    db_type: connection.db_type,
    host: connection.host,
    port: String(connection.port),
    database: connection.database,
    username: connection.username,
    password: "",
    ssl_enabled: connection.ssl_enabled,
  };
}

export function ConnectionForm({
  connection,
  onSuccess,
  onCancel,
}: ConnectionFormProps) {
  const isEdit = Boolean(connection?.id);
  const [form, setForm] = useState<FormState>(() => toFormState(connection));
  const [submitting, setSubmitting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [status, setStatus] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  useEffect(() => {
    setForm(toFormState(connection));
    setStatus(null);
  }, [connection]);

  const setField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleDbTypeChange = (dbType: string) => {
    setForm((prev) => {
      const prevDefault = DEFAULT_PORTS[prev.db_type];
      const nextDefault = DEFAULT_PORTS[dbType] ?? prev.port;
      const portNum = Number(prev.port);
      const shouldResetPort =
        !prev.port || Number.isNaN(portNum) || portNum === prevDefault;
      return {
        ...prev,
        db_type: dbType,
        port: shouldResetPort ? String(nextDefault) : prev.port,
      };
    });
  };

  const buildPayload = (): ConnectionCreate => {
    const port = Number(form.port);
    if (!form.name.trim()) throw new Error("Name is required");
    if (!form.host.trim()) throw new Error("Host is required");
    if (!Number.isFinite(port) || port <= 0) throw new Error("Port is invalid");
    if (!form.database.trim()) throw new Error("Database is required");
    if (!form.username.trim()) throw new Error("Username is required");
    if (!isEdit && !form.password) throw new Error("Password is required");

    return {
      name: form.name.trim(),
      db_type: form.db_type,
      host: form.host.trim(),
      port,
      database: form.database.trim(),
      username: form.username.trim(),
      password: form.password,
      ssl_enabled: form.ssl_enabled,
    };
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setStatus(null);
    setSubmitting(true);
    try {
      const payload = buildPayload();
      let saved: Connection;
      if (isEdit && connection) {
        const { password, ...rest } = payload;
        saved = await updateConnection(connection.id, {
          ...rest,
          ...(password ? { password } : {}),
        });
        setStatus({ type: "success", message: "Connection updated." });
      } else {
        saved = await createConnection(payload);
        setStatus({ type: "success", message: "Connection created." });
      }
      onSuccess(saved);
    } catch (err) {
      setStatus({
        type: "error",
        message: getErrorMessage(err, "Failed to save connection"),
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleTest = async () => {
    if (!connection?.id) {
      setStatus({
        type: "error",
        message: "Save the connection before testing.",
      });
      return;
    }
    setStatus(null);
    setTesting(true);
    try {
      const result = await testConnection(connection.id);
      setStatus({
        type: result.ok ? "success" : "error",
        message: result.message,
      });
    } catch (err) {
      setStatus({
        type: "error",
        message: getErrorMessage(err, "Connection test failed"),
      });
    } finally {
      setTesting(false);
    }
  };

  const fieldClass = "space-y-1";
  const labelClass = "block text-xs font-medium text-zinc-600";

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className={fieldClass}>
        <label htmlFor="conn-name" className={labelClass}>
          Name
        </label>
        <Input
          id="conn-name"
          value={form.name}
          onChange={(e) => setField("name", e.target.value)}
          placeholder="Production warehouse"
          required
          autoFocus
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className={fieldClass}>
          <label htmlFor="conn-db-type" className={labelClass}>
            Database type
          </label>
          <Select
            id="conn-db-type"
            value={form.db_type}
            onChange={(e) => handleDbTypeChange(e.target.value)}
          >
            {DB_TYPE_OPTIONS.map((opt) => (
              <option
                key={opt.value}
                value={opt.value}
                disabled={opt.disabled}
              >
                {opt.label}
              </option>
            ))}
          </Select>
        </div>
        <div className={fieldClass}>
          <label htmlFor="conn-port" className={labelClass}>
            Port
          </label>
          <Input
            id="conn-port"
            type="number"
            min={1}
            max={65535}
            value={form.port}
            onChange={(e) => setField("port", e.target.value)}
            required
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className={fieldClass}>
          <label htmlFor="conn-host" className={labelClass}>
            Host
          </label>
          <Input
            id="conn-host"
            value={form.host}
            onChange={(e) => setField("host", e.target.value)}
            placeholder="localhost"
            required
          />
        </div>
        <div className={fieldClass}>
          <label htmlFor="conn-database" className={labelClass}>
            Database
          </label>
          <Input
            id="conn-database"
            value={form.database}
            onChange={(e) => setField("database", e.target.value)}
            required
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className={fieldClass}>
          <label htmlFor="conn-username" className={labelClass}>
            Username
          </label>
          <Input
            id="conn-username"
            value={form.username}
            onChange={(e) => setField("username", e.target.value)}
            autoComplete="username"
            required
          />
        </div>
        <div className={fieldClass}>
          <label htmlFor="conn-password" className={labelClass}>
            Password
            {isEdit ? (
              <span className="ml-1 font-normal text-zinc-400">
                (leave blank to keep)
              </span>
            ) : null}
          </label>
          <Input
            id="conn-password"
            type="password"
            value={form.password}
            onChange={(e) => setField("password", e.target.value)}
            autoComplete="current-password"
            required={!isEdit}
            placeholder={isEdit && connection?.password_set ? "••••••••" : ""}
          />
        </div>
      </div>

      <label className="flex items-center gap-2 text-xs text-zinc-700">
        <input
          type="checkbox"
          checked={form.ssl_enabled}
          onChange={(e) => setField("ssl_enabled", e.target.checked)}
          className="h-3.5 w-3.5 rounded border-zinc-300 text-zinc-900 focus:ring-zinc-400"
        />
        SSL enabled
      </label>

      {status ? (
        <p
          className={
            status.type === "success"
              ? "text-xs text-emerald-700"
              : "text-xs text-red-600"
          }
          role="status"
        >
          {status.message}
        </p>
      ) : null}

      <div className="flex items-center justify-between gap-2 pt-1">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleTest}
          disabled={testing || submitting || !connection?.id}
          title={
            connection?.id
              ? "Test saved connection"
              : "Save the connection before testing"
          }
        >
          {testing ? <Spinner size="sm" /> : null}
          Test connection
        </Button>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onCancel}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button type="submit" size="sm" disabled={submitting || testing}>
            {submitting ? <Spinner size="sm" /> : null}
            {isEdit ? "Update" : "Create"}
          </Button>
        </div>
      </div>
    </form>
  );
}
