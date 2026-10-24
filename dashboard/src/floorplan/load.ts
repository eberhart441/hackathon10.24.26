// Fetch the hub's floor plan and validate it (Req 6.1, 6.3, 6.4). Never throws.
import type { FloorPlan, FloorplanError } from "./types";
import { validateFloorplan } from "./validate";

export const FLOORPLAN_PATH = "/api/floorplan";

export type FloorplanLoadResult =
  | { ok: true; plan: FloorPlan }
  /** The request never got an HTTP response (hub unreachable, TLS, aborted). */
  | { ok: false; kind: "network"; message: string }
  /** The hub answered with a non-2xx status. 401 means the token is missing or revoked. */
  | { ok: false; kind: "http"; status: number; message: string }
  /** The response was not JSON, or the floor plan broke one or more rules. */
  | { ok: false; kind: "invalid"; errors: FloorplanError[] };

async function errorText(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (typeof body === "object" && body !== null && "error" in body && typeof body.error === "string") {
      return body.error;
    }
  } catch {
    // Body was not JSON; fall through to a generic message.
  }
  if (res.status === 401) return "This phone is not paired with the hub, or its pairing was revoked.";
  return `The hub could not send the floor plan (HTTP ${res.status}).`;
}

export async function loadFloorplan(token: string, fetchImpl: typeof fetch = fetch): Promise<FloorplanLoadResult> {
  let res: Response;
  try {
    res = await fetchImpl(FLOORPLAN_PATH, {
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      cache: "no-store",
    });
  } catch (e) {
    const detail = e instanceof Error && e.message ? ` (${e.message})` : "";
    return { ok: false, kind: "network", message: `Could not reach the hub to load the floor plan${detail}.` };
  }

  if (!res.ok) {
    return { ok: false, kind: "http", status: res.status, message: await errorText(res) };
  }

  let body: unknown;
  try {
    body = await res.json();
  } catch {
    return {
      ok: false,
      kind: "invalid",
      errors: [{ rule: "schema", id: "floorplan", message: "The floor plan file is not valid JSON." }],
    };
  }

  const v = validateFloorplan(body);
  return v.ok ? { ok: true, plan: v.plan } : { ok: false, kind: "invalid", errors: v.errors };
}
