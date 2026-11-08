import type { components } from "./cardb-schema";
import { api, qs, type Caller } from "./http";
import { isUser, type Profile, type UiProfile } from "./profile";

type S = components["schemas"];
export type CarSummary = S["CarSummary"];
export type CarDetail = S["CarDetail"];
export type Stats = S["Stats"];
export type Status = S["Status"];
export type SellerType = S["SellerType"];
export type VerdictValue = S["VerdictValue"];
export type Verdict = NonNullable<S["Verdict"]>;
export type Note = S["Note"];
export type Message = S["Message"];
export type Event = S["Event"];
export type Listing = S["Listing"];
export type Option = S["Option"];
export type Fact = S["Fact"];
export type Photo = S["Photo"];
export type Seller = NonNullable<S["Seller"]>;
export type Contact = S["Contact"];
export type DuplicateCandidate = S["DuplicateCandidate"];
export type OptionValue = S["OptionValue"];
export type ModelFamilies = S["ModelFamilies"];
export type GoodDeal = S["GoodDeal"];
export type Queue = S["Queue"];
export type QueueItem = S["QueueItem"];
export type Powertrain = S["Powertrain"];
export type Fuel = S["Fuel"];

const V1 = "/api/v1";
const enc = encodeURIComponent;

export type CarQuery = Record<string, string | number | boolean | string[] | null | undefined>;

export function getProfile(who: Caller): Promise<Profile> {
  return api(who, `${V1}/profile`);
}

/** Reads on behalf of one viewer: verdicts, stats and the queue are that viewer's. */
export function cardb(who: Caller & { name: string }, profile: UiProfile) {
  const user = isUser(profile, who.name) ? who.name : undefined;
  return {
    listCars: (q: CarQuery): Promise<{ total: number; cars: CarSummary[] }> => api(who, `${V1}/cars${qs({ ...q, user })}`),
    getCar: (car: string | number): Promise<CarDetail> => api(who, `${V1}/cars/${enc(String(car))}${qs({ user })}`),
    getStats: (): Promise<Stats> => api(who, `${V1}/stats${qs({ user })}`),
    getModelFamilies: (): Promise<ModelFamilies> => api(who, `${V1}/model-families`),
    getQueue: (q: { tier?: string[]; spec?: string; limit?: number; offset?: number }): Promise<Queue> =>
      api(who, `${V1}/queue${qs({ tier: q.tier?.join(","), spec: q.spec || undefined, limit: q.limit, offset: q.offset, user })}`),
  };
}

export type Cardb = ReturnType<typeof cardb>;
