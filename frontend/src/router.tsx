import { type ReactNode } from "react";
import { createBrowserRouter, Navigate, Outlet } from "react-router-dom";
import { useAuth, usePermissions } from "./contexts/AuthContext";
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

function PermissionRoute({
  allowed,
  children,
}: {
  allowed: boolean;
  children: ReactNode;
}) {
  if (!allowed) {
    return <Navigate to="/chat" replace />;
  }
  return children;
}

function KnowledgeRoute() {
  const { canViewKnowledge } = usePermissions();
  return (
    <PermissionRoute allowed={canViewKnowledge}>
      <KnowledgePage />
    </PermissionRoute>
  );
}

function AgentRunsRoute() {
  const { canViewObservability } = usePermissions();
  return (
    <PermissionRoute allowed={canViewObservability}>
      <AgentRunsPage />
    </PermissionRoute>
  );
}

function BenchmarkRoute() {
  const { canReadBenchmark, canRunBenchmark } = usePermissions();
  return (
    <PermissionRoute allowed={canReadBenchmark || canRunBenchmark}>
      <BenchmarkDashboardPage />
    </PermissionRoute>
  );
}

function UsersRoute() {
  const { canManageUsers } = usePermissions();
  return (
    <PermissionRoute allowed={canManageUsers}>
      <UsersPage />
    </PermissionRoute>
  );
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
          { path: "knowledge", element: <KnowledgeRoute /> },
          { path: "agent-runs", element: <AgentRunsRoute /> },
          { path: "benchmark", element: <BenchmarkRoute /> },
          { path: "users", element: <UsersRoute /> },
        ],
      },
    ],
  },
]);
