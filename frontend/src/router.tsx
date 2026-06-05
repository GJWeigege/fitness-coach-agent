import { type ReactNode } from "react";
import { createBrowserRouter, Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./contexts/AuthContext";
import { MainLayout } from "./layouts/MainLayout";
import { AgentRunsPage } from "./pages/AgentRunsPage";
import { AuthPage } from "./pages/AuthPage";
import { BenchmarkDashboardPage } from "./pages/BenchmarkDashboardPage";
import { ChatPage } from "./pages/ChatPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { ProfilePage } from "./pages/ProfilePage";
import { UsersPage } from "./pages/UsersPage";

function LoadingScreen() {
  return (
    <div className="loading-screen">
      <div className="loading-spinner" />
      <p>Loading…</p>
    </div>
  );
}

function ProtectedRoute() {
  const { token, me, loading } = useAuth();

  if (loading) {
    return <LoadingScreen />;
  }

  if (!token || !me) {
    return <Navigate to="/auth" replace />;
  }

  return <Outlet />;
}

function GuestRoute({ children }: { children: ReactNode }) {
  const { token, me, loading } = useAuth();

  if (loading) {
    return <LoadingScreen />;
  }

  if (token && me) {
    return <Navigate to="/chat" replace />;
  }

  return children;
}

export const router = createBrowserRouter([
  {
    path: "/auth",
    element: (
      <GuestRoute>
        <AuthPage />
      </GuestRoute>
    ),
  },
  {
    path: "/",
    element: <ProtectedRoute />,
    children: [
      {
        element: <MainLayout />,
        children: [
          { index: true, element: <Navigate to="/chat" replace /> },
          { path: "chat", element: <ChatPage /> },
          { path: "profile", element: <ProfilePage /> },
          { path: "knowledge", element: <KnowledgePage /> },
          { path: "agent-runs", element: <AgentRunsPage /> },
          { path: "benchmark", element: <BenchmarkDashboardPage /> },
          { path: "users", element: <UsersPage /> },
        ],
      },
    ],
  },
]);
