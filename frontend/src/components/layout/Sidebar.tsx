import { type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useAuth, usePermissions } from "../../contexts/AuthContext";
import { Button } from "../ui/Button";
import {
  ActivityIcon,
  BookIcon,
  ChatIcon,
  ProfileIcon,
  ShieldIcon,
  SparkIcon,
} from "../ui/Icons";

type NavItem = {
  to: string;
  label: string;
  icon: ReactNode;
  visible: boolean;
};

export function Sidebar() {
  const { me, logout } = useAuth();
  const {
    canViewKnowledge,
    canViewObservability,
    canReadBenchmark,
    canRunBenchmark,
    canManageUsers,
  } = usePermissions();

  const navItems: NavItem[] = [
    { to: "/chat", label: "Chat", icon: <ChatIcon />, visible: true },
    { to: "/profile", label: "Profile", icon: <ProfileIcon />, visible: true },
    { to: "/knowledge", label: "Knowledge", icon: <BookIcon />, visible: canViewKnowledge },
    { to: "/agent-runs", label: "Agent Runs", icon: <ActivityIcon />, visible: canViewObservability },
    {
      to: "/benchmark",
      label: "评测",
      icon: <SparkIcon />,
      visible: canReadBenchmark || canRunBenchmark,
    },
    { to: "/users", label: "Users", icon: <ShieldIcon />, visible: canManageUsers },
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar__header">
        <div className="sidebar__title">
          <ChatIcon />
          <h2>Fitness Coach</h2>
        </div>
        {me ? (
          <p className="sidebar__user">
            {me.username} · {me.role}
          </p>
        ) : null}
      </div>
      <nav className="sidebar-nav" aria-label="Main navigation">
        {navItems
          .filter((item) => item.visible)
          .map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                isActive ? "sidebar-nav__link sidebar-nav__link--active" : "sidebar-nav__link"
              }
            >
              <span className="sidebar-nav__icon">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
      </nav>
      <div className="sidebar__footer">
        <Button variant="ghost" onClick={logout}>
          退出
        </Button>
      </div>
    </aside>
  );
}
