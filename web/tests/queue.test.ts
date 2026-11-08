import { describe, expect, it } from "vitest";
import { parseQueueParams, queueTiers, queueHref, hiddenTiers, queueSpecs, gapChip, tierTone, adBadge, adBadgeFromListings, listingStatus, adChips } from "@/lib/queue";
import { iconOptions, optionLabel } from "@/lib/vocab";

describe("queue params", () => {
  it("parses the all-tiers switch and clamps limit", () => {
    expect(parseQueueParams(new URLSearchParams(""))).toEqual({ all: false, spec: "", limit: 200 });
    expect(parseQueueParams(new URLSearchParams("all=1&limit=5000"))).toEqual({ all: true, spec: "", limit: 1000 });
    expect(parseQueueParams(new URLSearchParams("all=0&limit=abc&spec=bogus"))).toEqual({ all: false, spec: "", limit: 200 });
    expect(parseQueueParams(new URLSearchParams("spec=unknown")).spec).toBe("unknown");
  });
  it("takes tiers from the profile", () => {
    expect(queueTiers(false, [1, 2, 3], [1, 2])).toEqual(["1", "2"]);
    expect(queueTiers(true, [1, 2, 3], [1, 2])).toEqual(["1", "2", "3"]);
    expect(queueTiers(false, [], [])).toEqual([]);
    expect(hiddenTiers([1, 2, 3, 4], [1, 2])).toEqual([3, 4]);
    expect(hiddenTiers([1, 2], [1, 2])).toEqual([]);
    expect(tierTone(1)).toContain("accent");
    expect(tierTone(7)).toContain("muted");
  });
  it("builds hrefs without default params", () => {
    expect(queueHref({})).toBe("/queue");
    expect(queueHref({ all: true, limit: 200 })).toBe("/queue?all=1");
    expect(queueHref({ all: false, limit: 400 })).toBe("/queue?limit=400");
    expect(queueHref({ all: true, spec: "confirmed" })).toBe("/queue?all=1&spec=confirmed");
  });
  it("names the spec chips after the must-have options", () => {
    expect(queueSpecs([], optionLabel)).toEqual([]);
    const two = queueSpecs(["electric_seats", "power_tailgate"], optionLabel);
    expect(two[0]).toMatchObject({ value: "confirmed", label: "Electric seats + Power tailgate ✓", title: "Electric seats and Power tailgate all confirmed" });
    expect(two[1].value).toBe("unknown");
    expect(queueSpecs(["a", "b", "towbar"], optionLabel)[0].label).toBe("Must-haves ✓");
  });
});

describe("gapChip", () => {
  // cardb v2: positive price_gap_pct = cheaper than peers; the chip shows the price relative to fair.
  it("flips the sign, rounds and drops the make", () => {
    expect(gapChip(12.4, "VW ID.5 · 2025")).toEqual({ text: "−12 % vs ID.5 · 2025", tone: "bg-good-bg text-good" });
    expect(gapChip(-7.6, "Audi Q4 Sportback · all years")?.text).toBe("+8 % vs Q4 Sportback · all years");
    expect(gapChip(-7.6, "Audi Q4")?.tone).toBe("bg-bad-bg text-bad");
    expect(gapChip(0.2, "Kia EV6 2024")).toEqual({ text: "±0 % vs EV6 2024", tone: "bg-surface-2 text-muted" });
    expect(gapChip(null, "VW ID.4 2024")).toBeNull();
    expect(gapChip(3, null)?.text).toBe("−3 %");
  });
});

describe("ad badges", () => {
  it("car summary: removed beats gone, live hides", () => {
    expect(adBadge({ live_listing_count: 0, listing_count: 1, removed_listing_count: 1 })?.label).toBe("ad removed");
    expect(adBadge({ live_listing_count: 0, listing_count: 2, removed_listing_count: 0 })?.label).toBe("ad gone");
    expect(adBadge({ live_listing_count: 1, listing_count: 2, removed_listing_count: 1 })).toBeNull();
    expect(adBadge({ live_listing_count: 0, listing_count: 0, removed_listing_count: 0 })).toBeNull();
  });
  it("car page: from listing statuses", () => {
    expect(adBadgeFromListings([{ status: "removed" }, { status: "sold" }])?.kind).toBe("removed");
    expect(adBadgeFromListings([{ status: "sold" }])?.label).toBe("sold");
    expect(adBadgeFromListings([{ status: "unknown" }])?.label).toBe("ad gone");
    expect(adBadgeFromListings([{ status: "removed" }, { status: "live" }])).toBeNull();
    expect(listingStatus("removed")).toEqual({ label: "ad removed", tone: "bg-bad-bg text-bad" });
    expect(listingStatus(null).label).toBe("unknown");
  });
});

describe("ad chips", () => {
  const fmt = (v: number | null | undefined) => `${v} €`;
  it("puts live ads first and marks the rest", () => {
    const c = adChips([
      { url: "https://a/1", site: "marktplaats.nl", status: "removed", price: 36000 },
      { url: "https://b/1", site: "AutoScout24", status: "live", price: 36000 },
      { url: "https://a/2", site: "marktplaats.nl", status: "live", price: 34500 },
      { url: null, site: "mobile.de", status: "live" },
    ], fmt);
    expect(c.map((x) => x.url)).toEqual(["https://b/1", "https://a/2", "https://a/1"]);
    expect(c[0]).toMatchObject({ label: "AutoScout24", live: true, note: null });
    expect(c[1].label).toBe("marktplaats.nl · 34500 €");
    expect(c[2]).toMatchObject({ live: false, note: "ad removed", status: "removed" });
  });
  it("labels a site-less sold ad", () => {
    expect(adChips([{ url: "https://x", status: "sold" }], fmt)[0]).toMatchObject({ site: "ad", label: "ad", note: "sold" });
    expect(adChips([], fmt)).toEqual([]);
  });
});

describe("option icons", () => {
  const keys = ["electric_seats", "power_tailgate", "pano", "premium_audio"];
  it("maps yes/no/missing to three states with source", () => {
    const o = iconOptions(keys, { electric_seats: "yes", power_tailgate: "no", pano: "unknown" }, { electric_seats: "photo", power_tailgate: "seller_said" });
    expect(o.map((x) => [x.key, x.state])).toEqual([["electric_seats", "yes"], ["power_tailgate", "no"], ["pano", "unknown"], ["premium_audio", "unknown"]]);
    expect(o[0].info).toBe("Electric seats: yes · photo");
    expect(o[1].info).toBe("Power tailgate: no · seller said");
    expect(o[3].info).toBe("Premium audio: unknown");
  });

  it("labels the owner source with the owner's name, and unknown keys readably", () => {
    const o = iconOptions(["towbar", "ambient_light"], { towbar: "yes", ambient_light: "no" }, { towbar: "owner", ambient_light: "seller_said" }, "Sam");
    expect(o[0].info).toBe("Towbar: yes · Sam");
    expect(o[1].info).toBe("Ambient light: no · seller said");
  });
});
