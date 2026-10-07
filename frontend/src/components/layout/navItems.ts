import {
  Database,
  GitBranch,
  History,
  Layers,
  MessageSquare,
  Network,
  Settings,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
};

/** App primary nav — single source for App sidebar and chat session footer. */
export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Chat", icon: MessageSquare, end: true },
  { to: "/connections", label: "Connections", icon: Database },
  { to: "/context", label: "Context", icon: Layers },
  { to: "/schema", label: "Schema", icon: Network },
  { to: "/history", label: "History", icon: History },
  { to: "/agent", label: "Agent", icon: GitBranch },
  { to: "/settings", label: "Settings", icon: Settings },
];

/** Compact footer links shown in the chat session sidebar. */
export const CHAT_FOOTER_NAV: NavItem[] = NAV_ITEMS.filter((item) =>
  ["/connections", "/context", "/history", "/settings"].includes(item.to),
);
