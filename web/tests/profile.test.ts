import { describe, expect, it } from "vitest";
import { DEFAULT_ICON_KEYS, filterOptionKeys, homeLabel, iconKeys, isUser, needsLabel, roleOf, uiProfile } from "@/lib/profile";
import { engineLitres, powertrainRows, powertrainShort } from "@/lib/vocab";

const profile = uiProfile({
  owner: { name: "Sam", tz: "Europe/Berlin", home: { city: "Lisbon", country: "pt", lat: 38.7, lon: -9.1 } },
  users: [{ name: "Sam", role: "owner" }, { name: "Kim", role: "viewer" }],
  tiers: [{ tier: 2, label: "Good", rules: ["x"] }, { tier: 1, label: "Best", rules: [] }, { tier: 3 }],
  queue_default_tiers: [1, 2],
  option_keys: ["pano", "towbar"],
  options_wanted: { pano: 1.5, towbar: 3, heat_pump: 1, ugly_wheels: -0.5, keyless: 0.5 },
  must_have: ["electric_seats"],
  hard_filters: ["year ≥ 2021"],
  countries: ["pt", "ES"],
});

describe("profile", () => {
  it("normalizes the API profile", () => {
    expect(profile).toMatchObject({ ownerName: "Sam", tz: "Europe/Berlin", homeCity: "Lisbon", homeCountry: "PT", defaultTiers: [1, 2], countries: ["PT", "ES"], loaded: true });
    expect(profile.tiers.map((t) => t.tier)).toEqual([1, 2, 3]);
    expect(profile.tiers[2].label).toBe("Tier 3");
  });
  it("falls back to neutral words without a profile", () => {
    const p = uiProfile(null);
    expect(p).toMatchObject({ ownerName: "owner", tz: "UTC", loaded: false, tiers: [], defaultTiers: [] });
    expect(iconKeys(p)).toEqual(DEFAULT_ICON_KEYS);
    expect(homeLabel(p)).toBe("home");
    expect(uiProfile({ owner: { tz: "Mars/Olympus" }, users: [], tiers: [], option_keys: [], must_have: [], hard_filters: [] }).tz).toBe("UTC");
  });
  it("roles: users list, else owner by name, else other", () => {
    expect(roleOf(profile, "Kim")).toBe("viewer");
    expect(roleOf(profile, "Sam")).toBe("owner");
    expect(roleOf(profile, "web")).toBe("other");
    expect(isUser(profile, "Kim")).toBe(true);
    expect(isUser(profile, "web")).toBe(false);
  });
  it("icon row = must-haves, then heaviest wanted options, max 4", () => {
    expect(iconKeys(profile)).toEqual(["electric_seats", "towbar", "pano", "heat_pump"]);
    expect(filterOptionKeys(profile)).toEqual(["electric_seats", "towbar", "pano", "heat_pump", "ugly_wheels", "keyless"]);
  });
  it("labels from the owner and home", () => {
    expect(needsLabel(profile)).toBe("Needs Sam");
    expect(homeLabel(profile)).toBe("Lisbon");
  });
});

describe("powertrain", () => {
  it("short token per fuel", () => {
    expect(powertrainShort({ fuel: "bev", battery_net_kwh: 77 })).toBe("77 kWh");
    expect(powertrainShort({ fuel: "bev" })).toBe("EV");
    expect(powertrainShort({ fuel: "diesel", engine_cc: 1968, gearbox: "automatic" })).toBe("2.0 l diesel auto");
    expect(powertrainShort({ fuel: "phev", engine_cc: 1395, battery_net_kwh: 13 })).toBe("1.4 l PHEV 13 kWh");
    expect(powertrainShort({ battery_net_kwh: 58 })).toBe("58 kWh");
    expect(powertrainShort(null)).toBeNull();
    expect(engineLitres(1598)).toBe("1.6 l");
  });
  it("BEV block: battery, range, consumption, battery health", () => {
    const rows = powertrainRows({ fuel: "bev", battery_net_kwh: 77, battery_gross_kwh: 82, wltp_range_km: 520, wltp_consumption: 16.5, co2_g_km: 0 }, [{ key: "battery_soh", value: "94 % (certificate)" }, { key: "dpf", value: "n/a" }]);
    expect(rows).toEqual([
      ["Fuel", "Electric"],
      ["Battery", "77 net / 82 gross kWh"],
      ["Range", "520 km WLTP"],
      ["Consumption", "16.5 kWh/100 km"],
      ["Battery health", "94 % (certificate)"],
    ]);
  });
  it("ICE block: engine, gearbox, consumption, CO₂, engine health", () => {
    const rows = powertrainRows({ fuel: "petrol", engine_cc: 1498, gearbox: "manual", wltp_consumption: 6.1, co2_g_km: 139 }, [{ key: "timing_belt", value: "changed 2024" }, { key: "battery_soh", value: "?" }]);
    expect(rows).toEqual([
      ["Fuel", "Petrol"],
      ["Engine", "1.5 l"],
      ["Gearbox", "manual"],
      ["Consumption", "6.1 l/100 km"],
      ["CO₂", "139 g/km"],
      ["Timing belt", "changed 2024"],
    ]);
  });
});
