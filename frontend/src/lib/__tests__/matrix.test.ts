import { describe, expect, it } from "vitest";
import { cellStateClass, cellStateLabel } from "@/lib/matrix";

describe("matrix cell-state logic", () => {
  it("maps each state to a distinct label", () => {
    expect(cellStateLabel("ok")).toBe("OK");
    expect(cellStateLabel("verify")).toBe("Verify");
    expect(cellStateLabel("gap")).toBe("No quote");
  });

  it("maps each state to its colour class", () => {
    expect(cellStateClass("ok")).toContain("ok");
    expect(cellStateClass("verify")).toContain("verify");
    expect(cellStateClass("gap")).toContain("gap");
  });

  it("produces different classes per state", () => {
    const classes = new Set([
      cellStateClass("ok"),
      cellStateClass("verify"),
      cellStateClass("gap"),
    ]);
    expect(classes.size).toBe(3);
  });
});
