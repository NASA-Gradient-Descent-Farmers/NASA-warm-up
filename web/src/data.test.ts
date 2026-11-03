import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadProfile, loadStatic, nearestCell } from "./data";
import { DEFAULT_ECONOMICS, DEFAULT_PRIORITIES, DEFAULT_SCENARIO } from "./engine/core";
import { evaluate } from "./engine/evaluate";
import { explainCard } from "./ai/gemini";

const readAsset = (path: string) => readFileSync(new URL(`../public/data/${path}`, import.meta.url), "utf8");
const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } });
const html = () => new Response("<!doctype html><html></html>", { headers: { "content-type": "text/html" } });

function serveDemo() {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    try {
      return new Response(readAsset(url.split("data/")[1]), { headers: { "content-type": "application/json" } });
    } catch {
      // Reproduce Vite's response to a missing optional JSON.
      return html();
    }
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("demo data loading", () => {
  it("loads the existing Texcoco files, evaluates finite results and explains without Firebase", async () => {
    serveDemo();
    const data = await loadStatic();
    const hit = nearestCell(data.cells, 19.53, -98.85);
    expect(hit?.cell.region_id).toBe("texcoco_mx");
    const profile = await loadProfile(hit!.cell.cell_id);
    const result = evaluate({ profile, ...data, scenario: DEFAULT_SCENARIO, economics: DEFAULT_ECONOMICS,
      priorities: DEFAULT_PRIORITIES, existing: ["maize", "maize", "maize"] });
    expect(profile.years_sample.map((year) => year.year)).toEqual(Array.from({ length: 34 }, (_, i) => 1991 + i));
    expect(result.results.length).toBeGreaterThan(0);
    expect(result.front.length).toBeGreaterThan(0);
    expect(result.cards).toHaveLength(4);
    expect(result.cards[0].rotation.crops).toEqual(["maize", "maize", "maize"]);
    for (const rotation of result.results) {
      expect(Object.values(rotation.objectives).every(Number.isFinite)).toBe(true);
      expect(Number.isFinite(rotation.utility)).toBe(true);
      expect(rotation.lenses.twins.available).toBe(false);
    }
    const names = Object.fromEntries(data.crops.map((crop) => [crop.id, crop.name]));
    const explanation = await explainCard(result.cards[0], names, DEFAULT_SCENARIO, "English");
    expect(explanation.source).toBe("fallback");
    expect(explanation.explanation.summary).toContain("Maize");
    console.info(`Texcoco smoke: ${result.results.length} rotations, ${result.front.length} Pareto, ${result.nYears} years`);
  });

  it.each([404, 200])("allows a missing optional library (HTTP %s)", async (status) => {
    serveDemo();
    const original = globalThis.fetch;
    vi.stubGlobal("fetch", vi.fn((url: string) => url.endsWith("reference_sites.json")
      ? Promise.resolve(status === 404 ? new Response(null, { status }) : html())
      : original(url)));
    expect((await loadStatic()).references).toEqual([]);
  });

  it("reports a missing index as an empty set of available profiles", async () => {
    serveDemo();
    const original = globalThis.fetch;
    vi.stubGlobal("fetch", vi.fn((url: string) => url.endsWith("index.json") ? Promise.resolve(html()) : original(url)));
    expect((await loadStatic()).cells).toEqual([]);
  });

  it("reports required JSON served as HTML with an actionable error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => html()));
    await expect(loadStatic()).rejects.toThrow("Expected JSON for data/crops.json");
    await expect(loadProfile("missing")).rejects.toThrow("Expected JSON for data/profiles/missing.json");
  });

  it("does not hide malformed optional JSON or server errors", async () => {
    serveDemo();
    const original = globalThis.fetch;
    vi.stubGlobal("fetch", vi.fn((url: string) => url.endsWith("reference_sites.json")
      ? Promise.resolve(new Response("{broken", { headers: { "content-type": "application/json" } })) : original(url)));
    await expect(loadStatic()).rejects.toThrow("Invalid JSON in data/reference_sites.json");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 500 })));
    await expect(loadStatic()).rejects.toThrow("(500)");
  });

  it("refuses to calculate recommendations without historical weather", async () => {
    const profile = JSON.parse(readAsset("profiles/texcoco_mx_19.53_-98.85.json"));
    profile.years_sample = [];
    vi.stubGlobal("fetch", vi.fn(async () => json(profile)));
    await expect(loadProfile(profile.cell_id)).rejects.toThrow("No historical weather available");
  });
});
