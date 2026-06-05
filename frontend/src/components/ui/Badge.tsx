type BadgeVariant = "default" | "success" | "warning" | "danger" | "info";

const variantClass: Record<BadgeVariant, string> = {
  default: "badge--default",
  success: "badge--success",
  warning: "badge--warning",
  danger: "badge--danger",
  info: "badge--info",
};

export function Badge({ children, variant = "default" }: { children: React.ReactNode; variant?: BadgeVariant }) {
  return <span className={`badge ${variantClass[variant]}`}>{children}</span>;
}

export function statusVariant(status: string): BadgeVariant {
  const s = status.toLowerCase();
  if (s.includes("ready") || s.includes("done") || s.includes("indexed") || s.includes("completed")) {
    return "success";
  }
  if (s.includes("pending") || s.includes("processing") || s.includes("running")) return "warning";
  if (s.includes("fail") || s.includes("error")) return "danger";
  return "info";
}

export function roleVariant(role: string): BadgeVariant {
  if (role === "admin") return "danger";
  if (role === "kb_editor") return "info";
  return "default";
}
