import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import {
  AuthProvider,
  GuestOnly,
  RequireAuth,
  RequireSession,
} from "./auth/AuthProvider";
import ChatPage from "./pages/ChatPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import ConnectionsPage from "./pages/ConnectionsPage";
import ContextPage from "./pages/ContextPage";
import HistoryPage from "./pages/HistoryPage";
import LoginPage from "./pages/LoginPage";
import SettingsPage from "./pages/SettingsPage";
import { userPrefs } from "./lib/userPrefs";
import "./index.css";

const prefs = userPrefs.load();
document.documentElement.dataset.density = prefs.density;

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
        <AuthProvider>
          <Routes>
            <Route
              path="/login"
              element={
                <GuestOnly>
                  <LoginPage />
                </GuestOnly>
              }
            />
            <Route
              path="/change-password"
              element={
                <RequireSession>
                  <ChangePasswordPage />
                </RequireSession>
              }
            />
            <Route
              element={
                <RequireAuth>
                  <App />
                </RequireAuth>
              }
            >
              <Route index element={<ChatPage />} />
              <Route path="connections" element={<ConnectionsPage />} />
              <Route path="context" element={<ContextPage />} />
              <Route path="history" element={<HistoryPage />} />
              <Route path="settings" element={<SettingsPage />} />
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
