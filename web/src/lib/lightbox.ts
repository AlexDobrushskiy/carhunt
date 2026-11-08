// Pure helpers for the photo lightbox (src/components/PhotoLightbox.astro).

export interface LightboxItem {
  id: string;
  full: string;
  medium: string;
  caption: string;
}

export interface LightboxTrigger {
  photoId: string;
  caption?: string | null;
}

/** One item per photo id, in page order. Returns the items and, per trigger, the index it opens. */
export function buildItems(triggers: LightboxTrigger[]): { items: LightboxItem[]; indexOf: number[] } {
  const items: LightboxItem[] = [];
  const byId = new Map<string, number>();
  const indexOf = triggers.map((t) => {
    const known = byId.get(t.photoId);
    if (known != null) return known;
    byId.set(t.photoId, items.length);
    items.push({
      id: t.photoId,
      full: `/photos/${t.photoId}?size=full`,
      medium: `/photos/${t.photoId}?size=medium`,
      caption: t.caption ?? "",
    });
    return items.length - 1;
  });
  return { items, indexOf };
}

/** Next/previous index; wraps around at both ends. */
export function step(index: number, delta: number, count: number): number {
  if (count <= 0) return 0;
  return (((index + delta) % count) + count) % count;
}

/** Swipe direction from a finished touch: +1 next (finger moved left), -1 previous, 0 none. */
export function swipeDelta(dx: number, dy: number, min = 40): number {
  if (Math.abs(dx) < min || Math.abs(dx) < Math.abs(dy) * 1.2) return 0;
  return dx < 0 ? 1 : -1;
}
