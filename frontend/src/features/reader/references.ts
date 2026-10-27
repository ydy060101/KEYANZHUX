import type { Ref } from "./api";

/**
 * The entries a marker names, in the order the marker names them.
 *
 * The parser already resolved the marker to entry ids; re-deriving them from
 * the marker's text only works for numeric styles ("[11]" → index 11), so an
 * alpha-keyed marker ("[MCCD13, PSM14]") found nothing and the hover card said
 * "no entry" for every citation in a GPT-3-style bibliography.
 *
 * The order is the marker's, not the bibliography's: a card that lists
 * "[MCCD13, PSM14]" as PSM14 first is harder to check against the page.
 */
export function referencesFor(refIds: string[], references: Ref[]): Ref[] {
  const byId = new Map(references.map((reference) => [reference.id, reference]));
  const out: Ref[] = [];
  for (const id of refIds) {
    const reference = byId.get(id);
    if (reference) out.push(reference);
  }
  return out;
}
