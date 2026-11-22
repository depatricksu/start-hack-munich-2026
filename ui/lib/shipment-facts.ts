// What a request weighs and measures, as the clerk priced it.
// - weight_kg / volume_cbm are the model's own reading and can be one lot of several (request 55122: 1014 of 1898 kg).
//   weight_kg_total / volume_cbm_total are what the clerk priced after its own checks: those are shown.
// - A request with several shipments has no single weight: every shipment is shown ("1504 kg (553 + 951)").
import type { Fields } from "./types";

function several(f: Fields) {
  return Array.isArray(f.shipments) && f.shipments.length > 1 ? f.shipments : [];
}

function fact(f: Fields, key: "weight_kg" | "volume_cbm", unit: string): string | null {
  const parts = several(f).map((x) => Number(x[key]) || 0);
  if (parts.length && parts.every((p) => p > 0)) {
    const sum = Math.round(parts.reduce((a, b) => a + b, 0) * 100) / 100;
    return `${sum} ${unit} (${parts.join(" + ")})`;
  }
  const value = (key === "weight_kg" ? f.weight_kg_total : f.volume_cbm_total) ?? f[key];
  return value != null ? `${Math.round(Number(value) * 100) / 100} ${unit}` : null;
}

export const weightText = (f: Fields) => fact(f, "weight_kg", "kg");
export const volumeText = (f: Fields) => fact(f, "volume_cbm", "cbm");
