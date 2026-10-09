import { describe, expect, it } from "vitest";
import type { Problem } from "./api";
import { applyFilters, DEFAULT_FILTERS, failingLine, groupByGenre, heatmapCells, homeCopy, pickBest, progressText, rankScore, resolveId } from "./model";

const row = (o: Partial<Problem>): Problem => ({
  pid: "Amazon/X", id: "X", title: "t", corpus: "Amazon", tier: "B", genre: "g", genre_corpus: "g", family: "g", family_n: 1,
  rank: null, pubs: 1, confidence: 3, importance: 10, practice_stars: 0, practice_url: "", published: "", round: "", checks: 1,
  status: "", attempts: 0, solved_at: null, last_at: null, priority: 0, tags: [], ...o,
});
const rows = [
  row({ pid: "Amazon/A16", id: "A16", genre: "Specification/Filter", importance: 93, tier: "A", pubs: 2, family_n: 11 }),
  row({ pid: "Amazon/C07", id: "C07", genre: "intervals / sweep", importance: 30, priority: 5, status: "attempted", attempts: 2, tags: ["redo"] }),
  row({ pid: "Google/C07", id: "C07", corpus: "Google", genre: "tree", importance: 40, status: "solved", pubs: 2, family_n: 8 }),
  row({ pid: "Google/G44", id: "G44", corpus: "Google", genre: "tree", importance: 28, tier: "A" }),
];

describe("ranking and filters", () => {
  it("stars outrank importance", () => {
    expect(rankScore(rows[1])).toBe(5030);
    expect(applyFilters(rows, DEFAULT_FILTERS).map(r => r.pid)).toEqual(["Amazon/C07", "Amazon/A16", "Google/C07", "Google/G44"]);
  });
  it("filters by genre, status, corpus and search including tags", () => {
    expect(applyFilters(rows, { ...DEFAULT_FILTERS, genre: "tree" }).length).toBe(2);
    expect(applyFilters(rows, { ...DEFAULT_FILTERS, status: "fresh" }).map(r => r.id)).toEqual(["A16", "G44"]);
    expect(applyFilters(rows, { ...DEFAULT_FILTERS, corpus: "Google", status: "solved" }).map(r => r.pid)).toEqual(["Google/C07"]);
    expect(applyFilters(rows, { ...DEFAULT_FILTERS, q: "redo" }).map(r => r.pid)).toEqual(["Amazon/C07"]);
  });
  it("groups in order of the best row and counts solved", () => {
    const g = groupByGenre(applyFilters(rows, DEFAULT_FILTERS));
    expect(g.map(x => x.key)).toEqual(["intervals / sweep", "Specification/Filter", "tree"]);
    expect(g[2]).toMatchObject({ solved: 1, top: 40 });
  });
  it("picks the best unsolved and resolves ids", () => {
    expect(pickBest(rows)?.pid).toBe("Amazon/C07");
    expect(resolveId(rows, "a16")).toEqual({ pid: "Amazon/A16" });
    expect(resolveId(rows, "C07")).toEqual({ ambiguous: ["Amazon/C07", "Google/C07"] });
    expect(resolveId(rows, "google/c07")).toEqual({ pid: "Google/C07" });
    expect(resolveId(rows, "Z9")).toBeNull();
  });
});

describe("copy", () => {
  const now = Date.parse("2026-10-09T12:00:00Z");
  it("progress text reads like a sentence", () => {
    const base = { pid: "x", id: "x", title: "", genre: "tree", importance: 1, priority: 0, status: "", tier: "B", corpus: "Google" };
    expect(progressText({ ...base, attempts: 0, last_at: null }, now)).toBe("tree, not started");
    expect(progressText({ ...base, attempts: 2, last_at: now / 1000 - 3 * 86400 }, now)).toBe("tree, submitted twice 3 days ago");
    expect(progressText({ ...base, attempts: 0, last_at: now / 1000 - 86400 }, now)).toBe("tree, tests run yesterday, nothing submitted yet");
    expect(progressText({ ...base, attempts: 0, last_at: null, local: true }, now)).toBe("tree, draft saved in this browser");
  });
  it("home copy picks streak, then last accepted, and only calls a genre close when it is", () => {
    expect(homeCopy({ solved: 7, total: 250, streak: 3, last_ac_day: "2026-10-09", near: { genre: "DP", solved: 6, left: 2 }, top_genre: null }, now))
      .toEqual({ headline: "7 of 250 solved.", support: ["Three-day streak.", "DP is 2 problems from done."] });
    expect(homeCopy({ solved: 1, total: 250, streak: 0, last_ac_day: "2026-08-20", near: { genre: "binary search", solved: 1, left: 7 },
                      top_genre: { genre: "Specification/Filter", left: 11 } }, now).support)
      .toEqual(["Last accepted 2 months ago.", "Specification/Filter holds the highest-ranked problems, 11 still open."]);
    expect(homeCopy({ solved: 0, total: 250, streak: 0, last_ac_day: null, near: null, top_genre: null }, now).headline).toBe("250 problems, none solved yet.");
  });
  it("finds the failing editor line and builds heatmap cells", () => {
    expect(failingLine("tests line 3, in <module>:  check()\nyour code line 12, in f:  return x")).toBe(12);
    expect(failingLine("")).toBeUndefined();
    const cells = heatmapCells([{ ts: now, verdict: "AC" }], 4, new Date(now));
    expect(cells[cells.length - 1]).toMatchObject({ key: "2026-10-09", lvl: 2 });
    expect(cells.every(c => c.lvl >= 0 && c.lvl <= 4)).toBe(true);
  });
});
