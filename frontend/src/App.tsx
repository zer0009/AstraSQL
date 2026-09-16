import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  MessageSquare,
  Database,
  Layers,
  History,
  Settings,
} from "lucide-react";
import { cn } from "./lib/utils";
import { AstraLogo } from "./components/brand";
import { ScanStatusBanner } from "./components/ScanStatusBanner";

const navItems = [
  { to: "/", label: "Chat", icon: MessageSquare, end: true },
  { to: "/connections", label: "Connections", icon: Database, end: false },
  { to: "/context", label: "Context", icon: Layers, end: false },
  { to: "/history", label: "History", icon: History, end: false },
  { to: "/settings", label: "Settings", icon: Settings, end: false },
];

export default function App() {
  const location = useLocation();
  const isChatRoute = location.pathname === "/";

  return (
    <div className="flex h-screen overflow-hidden bg-zinc-50">
      {!isChatRoute ? (
        <aside className="flex w-56 shrink-0 flex-col border-r border-zinc-200 bg-white">
          <div className="flex h-12 items-center border-b border-zinc-200 px-4">
            <AstraLogo size={22} />
          </div>

          <nav className="flex flex-1 flex-col gap-0.5 p-2">
            {navItems.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-zinc-900 text-white"
                      : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900",
                  )
                }
              >
                <Icon className="h-4 w-4 shrink-0" strokeWidth={1.75} />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="border-t border-zinc-200 px-3 py-2">
            <p className="text-[11px] text-zinc-400">Self-hosted NL2SQL</p>
          </div>
        </aside>
      ) : null}

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <ScanStatusBanner />
        <Outlet />
      </main>
    </div>
  );
}
