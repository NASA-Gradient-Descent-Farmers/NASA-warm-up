import type { Crop, ReferenceSite, Rules, SiteProfile } from "./types";

export interface CellIndexEntry { cell_id: string; lat: number; lon: number; region_id: string; availability: Record<string, string> }
export interface Region { name: string; lat: number; lon: number }
export interface StaticData {
  crops: Crop[]; rules: Rules; references: ReferenceSite[]; cells: CellIndexEntry[]; regions: Record<string, Region>;
}

const base = import.meta.env.BASE_URL;

async function getJson<T>(path: string, optional = false): Promise<T | null> {
  const response = await fetch(`${base}data/${path}`);
  if (!response.ok) {
    if (optional && response.status === 404) return null;
    throw new Error(`Failed to load ${path} (${response.status})`);
  }
  // Vite's SPA fallback can return index.html with HTTP 200 for a missing JSON.
  if (!response.headers.get("content-type")?.includes("application/json")) {
    if (optional && response.headers.get("content-type")?.includes("text/html")) return null;
    throw new Error(`Expected JSON for data/${path}. Check web/public/data/ and the README startup steps.`);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new Error(`Invalid JSON in data/${path}. Check the file before retrying.`);
  }
}

export async function loadStatic(): Promise<StaticData> {
  const [crops, rules, refs, index] = await Promise.all([
    getJson<{ crops: Crop[] }>("crops.json"),
    getJson<Rules>("rotation_rules.json"),
    getJson<{ sites: ReferenceSite[] }>("reference_sites.json", true),
    getJson<{ cells: CellIndexEntry[]; regions: Record<string, Region> }>("index.json", true),
  ]);
  return { crops: crops!.crops, rules: rules!, references: refs?.sites ?? [], cells: index?.cells ?? [], regions: index?.regions ?? {} };
}

export async function loadProfile(cellId: string): Promise<SiteProfile> {
  const profile = (await getJson<SiteProfile>(`profiles/${cellId}.json`))!;
  if (profile.availability.weather?.status === "missing" || !profile.years_sample.length) {
    throw new Error(`No historical weather available for ${cellId}; recommendations cannot be calculated. See the README to generate the profile.`);
  }
  return profile;
}

export function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const rad = Math.PI / 180;
  const a = Math.sin(((lat2 - lat1) * rad) / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(a));
}

export function nearestCell(cells: CellIndexEntry[], lat: number, lon: number, maxKm = 80): { cell: CellIndexEntry; km: number } | null {
  let best: { cell: CellIndexEntry; km: number } | null = null;
  for (const cell of cells) {
    const km = haversineKm(lat, lon, cell.lat, cell.lon);
    if (!best || km < best.km) best = { cell, km };
  }
  return best && best.km <= maxKm ? best : null;
}

/** Typical current rotation (3-year cycle) by pilot region; used as the default "existing rotation". */
export const DEFAULT_EXISTING: Record<string, string[]> = {
  texcoco_mx: ["maize", "maize", "maize"],
  iowa_us: ["maize", "soybean", "maize"],
  punjab_in: ["wheat", "maize", "wheat"],
};
export const FALLBACK_EXISTING = ["maize", "maize", "maize"];

