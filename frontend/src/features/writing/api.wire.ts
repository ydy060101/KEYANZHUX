/**
 * Payload guards shared by the writing studio's wire modules.
 *
 * The generated schema marks nearly every field optional, so each parser
 * validates a payload once and hands the components strict values; a record
 * without an identity is dropped rather than rendered as a half-invented item
 * (H02).
 */

export function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function optionalText(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

export function optionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.flatMap((item) => (record(item) ? [record(item) as Record<string, unknown>] : []))
    : [];
}
