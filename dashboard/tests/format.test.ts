import { describe, expect, it } from "vitest";
import { formatAge, parseAge } from "../src/scene/format";
import { BANNED, STRINGS, hasBannedWord } from "../src/scene/strings";

describe("formatAge", () => {
  it.each([
    [0, "0:00"],
    [42, "0:42"],
    [60, "1:00"],
    [3599, "59:59"],
    [3600, "1:00:00"],
    [3725, "1:02:05"],
  ])("%s s -> %s", (s, text) => {
    expect(formatAge(s)).toBe(text);
  });

  it("floors fractions", () => {
    expect(formatAge(42.9)).toBe("0:42");
  });

  it("clamps negatives and non-finite values to 0", () => {
    expect(formatAge(-5)).toBe("0:00");
    expect(formatAge(Number.NaN)).toBe("0:00");
    expect(formatAge(Number.POSITIVE_INFINITY)).toBe("0:00");
  });
});

describe("parseAge", () => {
  it("inverts formatAge", () => {
    for (const s of [0, 42, 59, 60, 3599, 3600, 3725, 86399]) {
      expect(parseAge(formatAge(s))).toBe(s);
    }
  });

  it("rejects text formatAge never produces", () => {
    expect(parseAge("0:60")).toBeNaN();
    expect(parseAge("60:00")).toBeNaN();
    expect(parseAge("0:00:05")).toBeNaN();
    expect(parseAge("abc")).toBeNaN();
  });
});

describe("STRINGS", () => {
  it("contains no Banned_Word", () => {
    for (const [key, value] of Object.entries(STRINGS)) {
      expect(BANNED.test(value), `${key}: ${value}`).toBe(false);
    }
  });

  it("has the required copy", () => {
    expect(STRINGS.disclaimer).toBe("Decision support only — does not replace a full search");
    expect(STRINGS.stillNeedsSweep).toBe("Still needs a sweep");
    expect(STRINGS.allSearched).toBe("No detection rooms still require a sweep");
    expect(STRINGS.simulatedData).toBe("SIMULATED DATA");
    expect(STRINGS.reconnecting).toBe("Reconnecting…");
  });

  it("BANNED matches the banned words case-insensitively", () => {
    for (const w of ["empty", "Clear", "CLEARED", "safe"]) expect(hasBannedWord(`room ${w}`)).toBe(true);
    for (const w of ["Searched", "unclear", "safety"]) expect(hasBannedWord(w)).toBe(false);
  });
});
