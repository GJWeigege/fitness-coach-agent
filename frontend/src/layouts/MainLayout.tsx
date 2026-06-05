import { Outlet } from "react-router-dom";
import { Sidebar } from "../components/layout/Sidebar";
import { useApp } from "../contexts/AppContext";

export function MainLayout() {
  const { error, clearError } = useApp();

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <div className="app-content">
          <Outlet />
        </div>
        {error ? (
          <div className="toast toast--error" role="alert">
            <span>{error}</span>
            <button type="button" onClick={clearError} aria-label="关闭">
              ×
            </button>
          </div>
        ) : null}
      </main>
    </div>
  );
}
