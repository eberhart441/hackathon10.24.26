import { describe, expect, it } from "vitest";
import committedRaw from "../../hub/config/floorplan.json?raw";
import { validateFloorplan } from "../src/floorplan/validate";
import { loadFloorplan } from "../src/floorplan/load";

const committed = (): unknown => JSON.parse(committedRaw);

describe("validateFloorplan", () => {
  it("accepts the committed F1 floor plan", () => {
    const v = validateFloorplan(committed());
    expect(v.ok).toBe(true);
    if (!v.ok) return;
    expect(v.plan.floors.map((f) => f.id)).toEqual(["F1"]);
    expect(v.plan.floors.flatMap((f) => f.rooms.map((r) => r.id))).toEqual(["R1", "R2"]);
    expect(v.plan.floors[0]?.rooms.every((r) => r.simulated === false)).toBe(true);
  });

  it("committed plan contains no MAC addresses", () => {
    expect(committedRaw).not.toMatch(/([0-9a-f]{2}:){5}/i);
  });

  it("reports a door that runs past its wall with a plain-language message", () => {
    const plan = committed() as { floors: { rooms: { doors: { wall: number; offset: number; width: number }[] }[] }[] };
    const r2 = plan.floors[0]!.rooms[1]!;
    r2.doors.push({ wall: 0, offset: 3.2, width: 0.9, swing: "in" } as never);
    // R2 wall 0 is 1.54 m long.
    const v = validateFloorplan(plan);
    expect(v.ok).toBe(false);
    if (v.ok) return;
    expect(v.errors).toEqual([
      {
        rule: "door",
        id: "R2",
        message: 'Room "R2": door 1 runs past the end of wall 0 (offset 3.2 m + width 0.9 m > wall 1.54 m).',
      },
    ]);
  });

  it("collects several errors at once without throwing", () => {
    const plan = committed() as {
      floors: { rooms: { id: string; polygon: number[][] }[] }[];
      nodes: { id: string; room: string }[];
      links: { tx: string; rx: string }[];
    };
    plan.floors[0]!.rooms[0]!.polygon = [[0, 0], [1, 1], [2, 2]]; // zero area
    plan.nodes[3]!.room = "R9"; // missing room
    plan.links.push({ tx: "RX1", rx: "TX9" }); // wrong role + missing node
    const v = validateFloorplan(plan);
    expect(v.ok).toBe(false);
    if (v.ok) return;
    const rules = v.errors.map((e) => `${e.rule}:${e.id}`);
    expect(rules).toContain("polygon:R1");
    expect(rules).toContain("node_room:RX2");
    expect(rules).toContain("link:RX1→TX9");
    expect(v.errors.filter((e) => e.rule === "link")).toHaveLength(2);
  });

  it("reports duplicate room ids", () => {
    const plan = committed() as { floors: { rooms: { id: string }[] }[]; nodes: { room: string }[] };
    plan.floors[0]!.rooms[1]!.id = "R1";
    const v = validateFloorplan(plan);
    expect(v.ok).toBe(false);
    if (v.ok) return;
    expect(v.errors).toContainEqual({
      rule: "duplicate_id",
      id: "R1",
      message: 'Duplicate room id "R1": each room id must be unique.',
    });
  });

  it("returns schema errors for non-object input", () => {
    for (const bad of [null, 42, "x", [], { floors: "nope" }]) {
      const v = validateFloorplan(bad);
      expect(v.ok).toBe(false);
    }
  });
});

describe("loadFloorplan", () => {
  it("sends the bearer token and validates the response", async () => {
    let auth: string | null = null;
    const fake: typeof fetch = async (_url, init) => {
      auth = new Headers(init?.headers).get("Authorization");
      return new Response(committedRaw, { status: 200, headers: { "Content-Type": "application/json" } });
    };
    const r = await loadFloorplan("tok123", fake);
    expect(auth).toBe("Bearer tok123");
    expect(r.ok).toBe(true);
  });

  it("returns typed results for HTTP and network failures", async () => {
    const http = await loadFloorplan("t", async () =>
      new Response(JSON.stringify({ error: "Floor plan file could not be read: x" }), { status: 500 }),
    );
    expect(http).toEqual({ ok: false, kind: "http", status: 500, message: "Floor plan file could not be read: x" });

    const net = await loadFloorplan("t", async () => {
      throw new TypeError("Failed to fetch");
    });
    expect(net.ok).toBe(false);
    if (!net.ok) expect(net.kind).toBe("network");
  });
});
