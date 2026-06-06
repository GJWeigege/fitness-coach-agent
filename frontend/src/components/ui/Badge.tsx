import type { BadgeVariant } from "./badgeVariants";

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
