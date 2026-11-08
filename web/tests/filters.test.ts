import { describe, expect, it } from "vitest";
import { parseFilters, toApiQuery, activeFilterCount, hrefWith, resolveFamilies, familyGroups, familySummary } from "@/lib/filters";

describe("filters", () => {
  it("defaults to the active view sorted by activity", () => {
    const f = parseFilters(new URLSearchParams(""));
    expect(f.view).toBe("active");
    const q = toApiQuery(f);
    expect(q.status).toEqual(["new", "to_contact", "contacted", "talking", "ready_to_visit", "visited"]);
    expect(q.sort).toBe("last_activity");
    expect(activeFilterCount(f)).toBe(0);
  });

  it("maps form params to API params; explicit status overrides the view", () => {
    const f = parseFilters(new URLSearchParams("view=talking&price_max=40 000&country=PT&country=ES&status=dropped&opt_pano=yes&opt_power_tailgate=yes_or_unknown&opt_towbar=yes&sort=price&order=asc&model=EQB"), ["pano", "power_tailgate"]);
    const q = toApiQuery(f);
    expect(q).toMatchObject({ price_max: 40000, country: ["PT", "ES"], status: ["dropped"], sort: "price", order: "asc", model: "EQB" });
    expect(q.option).toEqual(["pano:yes", "power_tailgate:yes_or_unknown"]);
    expect(activeFilterCount(f)).toBe(6);
  });

  it("ignores junk values", () => {
    const f = parseFilters(new URLSearchParams("view=nope&sort=evil&opt_pano=maybe&km_max=abc&market=moon"), ["pano"]);
    expect(f.view).toBe("active");
    expect(f.sort).toBe("last_activity");
    expect(f.options).toEqual({});
    expect(f.nums).toEqual({});
    expect(f.market).toBe("");
  });

  it("view tabs keep other filters", () => {
    expect(hrefWith(new URLSearchParams("view=all&price_max=30000"), { view: "liked" })).toBe("/?view=liked&price_max=30000");
  });
});

it("keeps hp bounds and multiple drives through query, view changes and badge", () => {
  const sp = new URLSearchParams("view=all&hp_min=204&hp_max=299&drive=rwd&drive=awd");
  const f = parseFilters(sp);
  expect(toApiQuery(f)).toMatchObject({ hp_min: 204, hp_max: 299, drive: ["rwd", "awd"] });
  expect(activeFilterCount(f)).toBe(3);
  expect(hrefWith(sp, { view: "liked" })).toContain("hp_min=204&hp_max=299&drive=rwd&drive=awd");
  expect(toApiQuery(parseFilters(new URLSearchParams("hp_max=0")))).toMatchObject({ hp_max: 0 });
});

describe("good deal and model family filters", () => {
  it("maps good_deal=1 to the API flag and counts it", () => {
    const f = parseFilters(new URLSearchParams("view=all&good_deal=1"));
    expect(f.goodDeal).toBe(true);
    expect(toApiQuery(f)).toMatchObject({ good_deal: true });
    expect(activeFilterCount(f)).toBe(1);
    const off = parseFilters(new URLSearchParams("view=all&good_deal=0"));
    expect(off.goodDeal).toBe(false);
    expect(toApiQuery(off).good_deal).toBeUndefined();
  });

  it("collects repeated and comma-joined family values into model_family", () => {
    const f = parseFilters(new URLSearchParams("family=Audi+Q4&family=VW+ID.4,none&family=Audi+Q4&family="));
    expect(f.families).toEqual(["Audi Q4", "VW ID.4", "none"]);
    expect(toApiQuery(f).model_family).toEqual(["Audi Q4", "VW ID.4", "none"]);
    expect(activeFilterCount(f)).toBe(1);
    expect(toApiQuery(parseFilters(new URLSearchParams(""))).model_family).toBeUndefined();
  });

  it("keeps the legacy model substring param, counted, alongside families and good deal", () => {
    const f = parseFilters(new URLSearchParams("model=EQB&family=Mercedes+EQA&good_deal=1"));
    expect(toApiQuery(f)).toMatchObject({ model: "EQB", model_family: ["Mercedes EQA"], good_deal: true });
    expect(activeFilterCount(f)).toBe(3);
  });

  it("resolves URL families to canonical names and drops unknown ones", () => {
    const known = ["Audi Q4", "Škoda Enyaq", "VW ID.4"];
    expect(resolveFamilies(["audi q4", "Skoda Enyaq", "None", "Tesla Roadster", "VW ID.4", "vw id.4"], known)).toEqual(["Audi Q4", "Škoda Enyaq", "none", "VW ID.4"]);
    expect(resolveFamilies(["Whatever"], null)).toEqual(["Whatever"]);
  });

  it("groups families by make with short labels; selected but absent names go last", () => {
    const g = familyGroups(
      [
        { family: "Audi Q4", make: "Audi", count: 3 },
        { family: "Audi Q4 Sportback", make: "Audi", count: 2 },
        { family: "VW ID.4", make: "VW", count: 5 },
      ],
      ["VW ID.4", "Tesla Model Y", "none"],
    );
    expect(g.map((x) => x.make)).toEqual(["Audi", "VW", "No cars now"]);
    expect(g[0].items).toEqual([
      { family: "Audi Q4", label: "Q4", count: 3 },
      { family: "Audi Q4 Sportback", label: "Q4 Sportback", count: 2 },
    ]);
    expect(g[2].items).toEqual([{ family: "Tesla Model Y", label: "Tesla Model Y", count: 0 }]);
    expect(familySummary([])).toBe("Any model");
    expect(familySummary(["Audi Q4", "none"])).toBe("Audi Q4, Unmapped");
  });

  it("accepts the deal_rank sort", () => {
    expect(toApiQuery(parseFilters(new URLSearchParams("sort=deal_rank")))).toMatchObject({ sort: "deal_rank" });
  });
});

describe("distance, market, fuel and needs-owner filters", () => {
  it("maps distance, market, fuel and needs_owner", () => {
    const f = parseFilters(new URLSearchParams("view=needs&distance_km_max=300&market=home&fuel=bev&fuel=diesel&sort=distance_km"));
    const q = toApiQuery(f);
    expect(q).toMatchObject({ needs_owner: true, distance_km_max: 300, market: "home", fuel: ["bev", "diesel"], sort: "distance_km" });
    expect(activeFilterCount(f)).toBe(3);
    expect(parseFilters(new URLSearchParams("market=PT")).market).toBe("");
    expect(parseFilters(new URLSearchParams("sort=score")).sort).toBe("score");
  });
});
