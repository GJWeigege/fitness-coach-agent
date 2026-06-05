import { createBrowserRouter, Navigate } from "react-router-dom";
import { MainLayout } from "./layouts/MainLayout";
import { AgentRunsPage } from "./pages/AgentRunsPage";
import { AuthPage } from "./pages/AuthPage";
import { BenchmarkDashboardPage } from "./pages/BenchmarkDashboardPage";
import { ChatPage } from "./pages/ChatPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { ProfilePage } from "./pages/ProfilePage";
import { UsersPage } from "./pages/UsersPage";

export const router = createBrowserRouter([
  {
    path: "/auth",
    element: <AuthPage />,
  },
  {
    path: "/",
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
]);
