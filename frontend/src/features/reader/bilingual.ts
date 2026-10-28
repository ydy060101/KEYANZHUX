/**
 * Block-level geometry for the bilingual reader (T4.3).
 *
 * Both columns are synchronized through block identity, never through a
 * scroll-ratio: a PDF block's top is `page offset + bbox.y * scale`, a
 * translation row's top is its own DOM offset, and the block that crosses the
 * reading line wins. Keeping the picker pure makes the ordering rule testable
 * without a laid-out browser.
 */

export interface Positioned {
  id: string;
  /** Distance from the scroll container's content origin, in CSS pixels. */
  top: number;
  bottom: number;
}

/**
 * The item a reader is looking at when the reading line is at `line`.
 *
 * Prefer the nearest item that starts at or above the line; when everything
 * starts below it (the top of a document), take the nearest one below. Ties
 * keep the later item, which matches reading order on the same baseline.
 */
export function pickAtLine(items: readonly Positioned[], line: number): Positioned | null {
  let before: Positioned | null = null;
  let after: Positioned | null = null;
  for (const item of items) {
    if (item.top <= line) {
      if (!before || item.top >= before.top) before = item;
    } else if (!after || item.top < after.top) {
      after = item;
    }
  }
  return before ?? after;
}

/** A node's top in the scroll container's content coordinates. */
export function offsetWithin(host: HTMLElement, node: HTMLElement): number {
  return node.getBoundingClientRect().top - host.getBoundingClientRect().top + host.scrollTop;
}

/** A PDF block's top in the PDF scroll container's content coordinates. */
export function bboxTop(
  host: HTMLElement,
  pageNode: HTMLElement,
  bbox: readonly number[],
  scale: number,
): number {
  return offsetWithin(host, pageNode) + (bbox[1] ?? 0) * scale;
}
