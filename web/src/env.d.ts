/// <reference path="../.astro/types.d.ts" />

declare namespace App {
  interface Locals {
    viewer: import("./lib/identity").Viewer & { role: import("./lib/profile").Role };
    profile: import("./lib/profile").UiProfile;
    db: import("./lib/cardb").Cardb;
  }
}
