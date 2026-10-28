/**
 * Wire layer for the writing studio (T7.5): `/writing`, `/figures`, `/data`
 * and `/translate/zh2en`.
 *
 * The layer is split by domain (`api.types`, `api.outline`, `api.workshop`,
 * `api.download`) so no file approaches the 400-line limit. Components keep
 * importing from this module; the parsers validate every payload once and give
 * the components strict values.
 */

export * from "./api.types";
export * from "./api.outline";
export * from "./api.workshop";
export * from "./api.download";
