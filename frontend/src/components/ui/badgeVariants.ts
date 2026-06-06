export type BadgeVariant = "default" | "success" | "warning" | "danger" | "info";

export function statusVariant(status: string): BadgeVariant {
  const s = status.toLowerCase();
  if (s.includes("ready") || s.includes("done") || s.includes("indexed") || s.includes("completed")) {
    return "success";
  }
  if (s.includes("pending") || s.includes("processing") || s.includes("running")) return "warning";
  if (s.includes("cancel")) return "info";
  if (s.includes("fail") || s.includes("error")) return "danger";
  return "info";
}

export function roleVariant(role: string): BadgeVariant {
  if (role === "admin") return "danger";
  if (role === "kb_editor") return "info";
  return "default";
}
