import type { CellState } from "@/lib/api";

export function cellStateClass(state: CellState): string {
  switch (state) {
    case "ok":
      return "bg-ok/10 border-ok/30";
    case "verify":
      return "bg-verify/10 border-verify/40";
    case "gap":
      return "bg-gap/10 border-gap/30";
    default:
      return "";
  }
}

export function cellStateLabel(state: CellState): string {
  switch (state) {
    case "ok":
      return "OK";
    case "verify":
      return "Verify";
    case "gap":
      return "No quote";
    default:
      return "";
  }
}

export function cellStateBadge(state: CellState): "ok" | "verify" | "gap" {
  return state;
}
