import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import ChatPage from "./pages/ChatPage";
import ConnectionsPage from "./pages/ConnectionsPage";
import ContextPage from "./pages/ContextPage";
import HistoryPage from "./pages/HistoryPage";
import SettingsPage from "./pages/SettingsPage";
import "./index.css";

const savedDensity = localStorage.getItem("astrasql.ui.density");
if (savedDensity === "compact" || savedDensity === "comfortable") {
  document.documentElement.dataset.density = savedDensity;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<App />}>
            <Route index element={<ChatPage />} />
            <Route path="connections" element={<ConnectionsPage />} />
            <Route path="context" element={<ContextPage />} />
            <Route path="history" element={<HistoryPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
