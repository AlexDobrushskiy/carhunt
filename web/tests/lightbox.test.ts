import { describe, expect, it } from "vitest";
import { buildItems, step, swipeDelta } from "@/lib/lightbox";

describe("buildItems", () => {
  it("keeps page order and maps a repeated photo to its first index", () => {
    const { items, indexOf } = buildItems([
      { photoId: "10", caption: "1/2" },
      { photoId: "11", caption: "2/2 · from seller" },
      { photoId: "11" },
      { photoId: "12", caption: null },
    ]);
    expect(items.map((i) => i.id)).toEqual(["10", "11", "12"]);
    expect(indexOf).toEqual([0, 1, 1, 2]);
    expect(items[1]).toEqual({ id: "11", full: "/photos/11?size=full", medium: "/photos/11?size=medium", caption: "2/2 · from seller" });
    expect(items[2].caption).toBe("");
  });
});

describe("step", () => {
  it("wraps at both ends", () => {
    expect(step(0, -1, 26)).toBe(25);
    expect(step(25, 1, 26)).toBe(0);
    expect(step(2, 1, 26)).toBe(3);
    expect(step(0, 1, 1)).toBe(0);
    expect(step(0, 1, 0)).toBe(0);
  });
});

describe("swipeDelta", () => {
  it("needs a mostly horizontal move past the threshold", () => {
    expect(swipeDelta(-120, 10)).toBe(1);
    expect(swipeDelta(120, -5)).toBe(-1);
    expect(swipeDelta(-30, 0)).toBe(0);
    expect(swipeDelta(-80, 90)).toBe(0);
  });
});
