import { NavLink } from "react-router-dom";

const navItems = [
  { to: "/chat", label: "Chat" },
  { to: "/profile", label: "Profile" },
  { to: "/knowledge", label: "Knowledge" },
  { to: "/agent-runs", label: "Agent Runs" },
  { to: "/benchmark", label: "Benchmark" },
  { to: "/users", label: "Users" },
] as const;

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar__header">
        <h2>Fitness Coach</h2>
      </div>
      <nav className="sidebar-nav" aria-label="Main navigation">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              isActive ? "sidebar-nav__link sidebar-nav__link--active" : "sidebar-nav__link"
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
