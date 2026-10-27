import type { Citation } from "./api";
import { scaleFor } from "./pdf";

/**
 * Citation hit boxes over a page, from the bboxes the parser recorded (H01).
 *
 * The boxes are drawn on top of the rendered page rather than into the text
 * layer, so a marker that pdf.js does not lay out as selectable text — a
 * scanned page, an unusual glyph run — is still hoverable. Only the marker's
 * own rectangle is covered, never the paragraph it sits in.
 */
export function CitationOverlay({
  citations,
  zoom,
  onHover,
  onLeave,
  onOpen,
}: {
  citations: Citation[];
  zoom: number;
  onHover: (x: number, y: number, marker: string, citation: Citation) => void;
  onLeave: () => void;
  onOpen: (citation: Citation) => void;
}) {
  return (
    <>
      {citations.map((citation) => {
        if (!citation.bbox || citation.bbox.length !== 4) return null;
        const [x0, y0, x1, y1] = citation.bbox as [number, number, number, number];
        const scale = scaleFor(zoom);
        return (
          <button
            key={citation.id}
            type="button"
            aria-label={`引用 ${citation.marker}`}
            data-citation={citation.marker}
            onMouseEnter={(event) => {
              onHover(event.clientX, event.clientY + 18, citation.marker, citation);
            }}
            onMouseLeave={onLeave}
            onClick={() => {
              onOpen(citation);
            }}
            className="absolute rounded-[2px] bg-[var(--primary)]/10 hover:bg-[var(--primary)]/25"
            style={{
              left: x0 * scale,
              top: y0 * scale,
              width: Math.max(6, (x1 - x0) * scale),
              height: Math.max(6, (y1 - y0) * scale),
            }}
          />
        );
      })}
    </>
  );
}
