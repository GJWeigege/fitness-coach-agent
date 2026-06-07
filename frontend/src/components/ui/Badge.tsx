import type { ReactNode } from "react";
import type { BadgeVariant } from "./badgeVariants";

const variantClass: Record<BadgeVariant, string> = {
  default: "badge--default",
  success: "badge--success",
  warning: "badge--warning",
  danger: "badge--danger",
  info: "badge--info",
};

export function Badge({
  children,
  variant = "default",
  className,
}: {
  children: ReactNode;
  variant?: BadgeVariant;
  className?: string;
}) {
  return <span className={["badge", variantClass[variant], className].filter(Boolean).join(" ")}>{children}</span>;
}
