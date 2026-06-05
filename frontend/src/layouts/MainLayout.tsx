import { Outlet } from "react-router-dom";
import { Sidebar } from "../components/layout/Sidebar";

export function MainLayout() {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
