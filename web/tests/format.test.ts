import { describe, expect, it } from "vitest";
import { price, power, km, regDate, flag, ago, when, distance } from "@/lib/format";

describe("format", () => {
  it("formats money, mileage and dates", () => {
    expect(price(34600)).toBe("€34,600");
    expect(price(null)).toBe("—");
    expect(km(50000)).toBe("50k km");
    expect(km(800)).toBe("800 km");
    expect(regDate("2023-07")).toBe("07/2023");
    expect(regDate("2023-07-14")).toBe("07/2023");
    expect(flag("pt")).toBe("🇵🇹");
    expect(flag("JP")).toBe("🇯🇵");
    expect(flag("Wales")).toBe("Wales");
    expect(ago("2026-11-01T10:00:00Z", "UTC", new Date("2026-11-01T12:30:00Z"))).toBe("2h");
    expect(distance(120, "stored", "Lisbon")).toBe("120 km to Lisbon");
    expect(distance(1450, "estimate")).toBe("≈1,450 km");
    expect(distance(null, "stored")).toBeNull();
  });
  it("shows times in the owner's zone", () => {
    const now = new Date("2026-11-08T12:00:00Z");
    expect(when("2026-11-01T23:30:00Z", "UTC", now)).toBe("Sun 1 Nov 23:30");
    expect(when("2026-11-01T23:30:00Z", "Asia/Tokyo", now)).toBe("Mon 2 Nov 08:30");
  });
});

import { readableRef } from "@/lib/vocab";
describe("readableRef", () => {
  it("drops import provenance, keeps real evidence", () => {
    expect(readableRef("outreach: confirmed.accidents")).toBeNull();
    expect(readableRef("picker:")).toBeNull();
    expect(readableRef("outreach: facts.seats · Electric driver seat")).toBe("Electric driver seat");
    expect(readableRef("photo #3")).toBe("photo #3");
    expect(readableRef("PR code 9VS")).toBe("PR code 9VS");
  });
});

it("converts kW to rounded metric hp and preserves missing power", () => {
  expect(power(150)).toBe("204 hp");
  expect(power(125.4)).toBe("171 hp");
  expect(power(210)).toBe("286 hp");
  expect(power(0)).toBe("0 hp");
  expect(power(null)).toBe("—");
  expect(power(undefined)).toBe("—");
});
