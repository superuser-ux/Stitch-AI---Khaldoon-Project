import { test, expect } from "@playwright/test";
import { contentIdLabel, contentIdParts, resolveContentId, type ContentIdTarget } from "../lib/content-id";

// #49 (BUG-003) — bidirectional resolution between the canonical slot_id and the displayed content code.
// Pure logic: no dashboard/API needed.
const T = (over: Partial<ContentIdTarget>): ContentIdTarget => ({
  day: 1, slot_id: "RX-1", pillar_short_code: "P1", seq_in_pillar: 1, ...over,
});

// a round-scoped set with distinct codes: a=01-02-01.01, b=03-01-01.02, c=01-02-02.01
const a = T({ slot_id: "RX-D01-AM", day: 1, pillar_short_code: "P1", seq_in_pillar: 2 });
const b = T({ slot_id: "RX-D01-PM", day: 1, pillar_short_code: "P3", seq_in_pillar: 1 });
const c = T({ slot_id: "RX-D02-AM", day: 2, pillar_short_code: "P1", seq_in_pillar: 2 });
const round = [a, b, c];

test.describe("#49 content-id bidirectional resolution (pure logic)", () => {
  test("the canonical slot_id resolves to itself (case-insensitive)", () => {
    expect(resolveContentId(round, "RX-D01-AM")).toEqual({ ok: true, slot_id: "RX-D01-AM" });
    expect(resolveContentId(round, "rx-d01-am")).toEqual({ ok: true, slot_id: "RX-D01-AM" });
  });

  test("a displayed content code resolves to its internal slot (compact & expanded forms)", () => {
    expect(contentIdLabel(a, "compact")).toBe("01-02-01.01");
    expect(contentIdLabel(a, "expanded")).toBe("P01-HS02-01.01");
    expect(resolveContentId(round, "01-02-01.01")).toEqual({ ok: true, slot_id: "RX-D01-AM" });
    expect(resolveContentId(round, "P01-HS02-01.01")).toEqual({ ok: true, slot_id: "RX-D01-AM" });
    // formatting-invariant (spaces / missing separators)
    expect(resolveContentId(round, "01 02 01 01")).toEqual({ ok: true, slot_id: "RX-D01-AM" });
  });

  test("round-trip: every slot -> its code (each mode) -> back to the same slot", () => {
    for (const t of round) {
      for (const mode of ["compact", "expanded", "detailed"] as const) {
        expect(resolveContentId(round, contentIdLabel(t, mode))).toEqual({ ok: true, slot_id: t.slot_id });
      }
      expect(resolveContentId(round, t.slot_id)).toEqual({ ok: true, slot_id: t.slot_id });
    }
  });

  test("missing / blank identifiers are rejected safely (never guesses)", () => {
    expect(resolveContentId(round, "99-99-99.99")).toEqual({ ok: false, reason: "not_found", matches: [] });
    expect(resolveContentId(round, "NOPE-1")).toEqual({ ok: false, reason: "not_found", matches: [] });
    expect(resolveContentId(round, "")).toEqual({ ok: false, reason: "empty", matches: [] });
    expect(resolveContentId(round, "   ")).toEqual({ ok: false, reason: "empty", matches: [] });
    // a slot_id from ANOTHER round is out of the scoped set -> not_found (round-scoped uniqueness)
    expect(resolveContentId(round, "RY-D01-AM")).toEqual({ ok: false, reason: "not_found", matches: [] });
  });

  test("an ambiguous displayed code is rejected safely with all candidates", () => {
    const dup = T({ slot_id: "RX-D01-AM-DUP", day: 1, pillar_short_code: "P1", seq_in_pillar: 2 }); // same code as `a`
    expect(contentIdParts(dup)).toEqual(contentIdParts(a));
    const res = resolveContentId([a, dup], "01-02-01.01");
    expect(res).toEqual({ ok: false, reason: "ambiguous", matches: ["RX-D01-AM", "RX-D01-AM-DUP"] });
  });

  test("canonical slot_id match wins over a coincidental code match", () => {
    // querying an exact slot_id returns that slot even though the resolver also checks codes
    expect(resolveContentId(round, "RX-D02-AM")).toEqual({ ok: true, slot_id: "RX-D02-AM" });
  });
});
