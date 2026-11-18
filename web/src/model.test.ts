import { describe, expect, it } from "vitest";
import type { Card, Daily, Mock, Pet, Problem, Slim } from "./api";
import {
  paidNote, petCaption, petLook, petMoodLine, petProgress, petStatus, stageName, xpLine,
  mockHeadline, mockHistoryLine, mockLeft, mockName, mockProblemLine,
  cardLabel, cardQuestion, clockText, comesBack, debriefCards, debriefFacts, debriefHeadline, durationText, reviewCopy,
  applyFilters, dailyCopy, dayText, DEFAULT_FILTERS, difficultyRank, failingLine, groupByGenre, heatmapCells, homeCopy, ladderSteps,
  minutesShort, minutesText, pickBest, progressText, rankScore, redoState, redoText, resolveId, rowStatus, serverNow, sizeSentence, syncClock,
} from "./model";

const row = (o: Partial<Problem>): Problem => ({
  pid: "Amazon/X", id: "X", title: "t", corpus: "Amazon", tier: "B", genre: "g", genre_corpus: "g", family: "g", family_n: 1,
  rank: null, pubs: 1, confidence: 3, importance: 10, practice_stars: 0, practice_url: "", published: "", round: "", checks: 1,
  status: "", attempts: 0, solved_at: null, last_at: null, priority: 0, tags: [],
  difficulty: "Medium", difficulty_src: "twin", minutes: 30, loc: 60, hints: 0, redo_at: null, redo_why: "", ...o,
});
const slim = (o: Partial<Slim>): Slim => ({
  pid: "Amazon/X", id: "X", title: "Flood Fill", genre: "graph", importance: 44, priority: 0, status: "", attempts: 0, last_at: null,
  tier: "B", corpus: "Amazon", difficulty: "Easy", difficulty_src: "twin", minutes: 15, redo_at: null, redo_why: "", ...o,
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
    const base = slim({ pid: "x", id: "x", title: "", genre: "tree", importance: 1, corpus: "Google" });
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

describe("difficulty, time and redo", () => {
  const now = Date.parse("2026-11-17T12:00:00");
  const sec = (iso: string) => Date.parse(iso) / 1000;
  const set = [
    row({ pid: "Amazon/H", id: "H", difficulty: "Hard", minutes: 30, importance: 90 }),
    row({ pid: "Amazon/E2", id: "E2", difficulty: "Easy", minutes: 30, importance: 20 }),
    row({ pid: "Amazon/E1", id: "E1", difficulty: "Easy", minutes: 15, importance: 10 }),
    row({ pid: "Amazon/M", id: "M", difficulty: "Medium", minutes: 15, importance: 50 }),
    row({ pid: "Amazon/U", id: "U", difficulty: "", minutes: 0, importance: 99 }),
  ];
  it("sorts easiest first and shortest first, unrated last", () => {
    expect(applyFilters(set, { ...DEFAULT_FILTERS, sort: "easiest" }).map(r => r.id)).toEqual(["E1", "E2", "M", "H", "U"]);
    expect(applyFilters(set, { ...DEFAULT_FILTERS, sort: "shortest" }).map(r => r.id)).toEqual(["E1", "M", "E2", "H", "U"]);
    expect([difficultyRank("Easy"), difficultyRank("Hard"), difficultyRank("")]).toEqual([1, 3, 9]);
  });
  it("filters by difficulty and treats a pending redo as its own status", () => {
    const rs = [
      row({ pid: "Amazon/A", id: "A", status: "solved", redo_at: sec("2026-11-20T09:00:00") }),
      row({ pid: "Amazon/B", id: "B", redo_at: sec("2026-11-16T09:00:00") }),
      row({ pid: "Amazon/C", id: "C", difficulty: "Easy" }),
      row({ pid: "Amazon/D", id: "D", status: "solved" }),
    ];
    expect(applyFilters(rs, { ...DEFAULT_FILTERS, difficulty: "Easy" }).map(r => r.id)).toEqual(["C"]);
    expect(applyFilters(rs, { ...DEFAULT_FILTERS, status: "redo" }).map(r => r.id)).toEqual(["A", "B"]);
    expect(applyFilters(rs, { ...DEFAULT_FILTERS, status: "fresh" }).map(r => r.id)).toEqual(["C"]);
    expect(applyFilters(rs, { ...DEFAULT_FILTERS, status: "solved" }).map(r => r.id)).toEqual(["A", "D"]);
    expect(rs.map(rowStatus)).toEqual(["assisted", "assisted", "", "solved"]);
    expect(pickBest(rs)?.id).toBe("C");   // B rests until its redo, A and D are solved
    expect([redoState(null, now), redoState(rs[0].redo_at, now), redoState(rs[1].redo_at, now)]).toEqual(["none", "resting", "due"]);
  });
  it("writes sizes and days as words", () => {
    expect([minutesShort(15), minutesShort(60), minutesText(45), minutesText(60)]).toEqual(["15 min", "60+ min", "about 45 minutes", "about an hour"]);
    expect(sizeSentence({ difficulty: "Easy", genre: "graph", minutes: 15 })).toBe("Easy graph problem, about 15 minutes.");
    expect(sizeSentence({ difficulty: "", genre: "heap/top-k", minutes: 0 })).toBe("Heap/top-k problem.");
    expect(["2026-11-17T23:00:00", "2026-11-18T00:30:00", "2026-11-20T08:00:00", "2026-11-16T23:59:00", "2026-11-10T12:00:00"].map(d => dayText(sec(d), now)))
      .toEqual(["today", "tomorrow", "in 3 days", "yesterday", "7 days ago"]);
    expect(["2026-11-20T08:00:00", "2026-11-18T00:30:00", "2026-11-17T23:00:00", "2026-11-17T11:59:00", "2026-11-10T12:00:00"].map(d => redoText(sec(d), now)))
      .toEqual(["redo in 3 days", "redo tomorrow", "redo today", "redo due", "redo due"]);
  });
  it("follows the server's clock, not this device's", () => {
    const ahead = Math.floor(Date.now() / 1000) + 3 * 86400;     // the server says it is three days later
    syncClock(ahead);
    expect(Math.abs(serverNow() - ahead * 1000)).toBeLessThan(2000);
    expect(redoState(ahead - 60)).toBe("due");                   // due by the server's clock
    expect(redoText(ahead - 60)).toBe("redo due");
    syncClock(Math.floor(Date.now() / 1000));
    expect(redoState(ahead - 60)).toBe("resting");
  });
});

describe("today and the hint ladder", () => {
  const items = [slim({}), slim({ pid: "Amazon/Y", id: "Y", title: "Top K", difficulty: "Medium", genre: "heap/top-k" })];
  const daily = (o: Partial<Daily>): Daily => ({ kind: "pick", why: "ramp", budget: 15, due: 0, items, ...o });
  it("says why today's problem was picked, and only for the first pick", () => {
    expect(dailyCopy(daily({ why: "start" }))).toEqual({ title: "Flood Fill", sub: "Easy graph problem, about 15 minutes. A short one to get moving.", another: true });
    expect(dailyCopy(daily({ why: "back" }))?.sub).toBe("Easy graph problem, about 15 minutes. A short one to get back into it.");
    expect(dailyCopy(daily({ why: "ramp" }))?.sub).toBe("Easy graph problem, about 15 minutes.");
    expect(dailyCopy(daily({ why: "start" }), 1)).toEqual({ title: "Top K", sub: "Medium heap/top-k problem, about 15 minutes.", another: true });
    expect(dailyCopy(daily({ why: "start" }), 2)?.title).toBe("Flood Fill");   // wraps around
    expect(dailyCopy(daily({ items: [items[0]] }))?.another).toBe(false);
  });
  it("asks for a redo first and counts the ones behind it", () => {
    expect(dailyCopy(daily({ kind: "redo", why: "redo", due: 1 }))).toEqual({
      title: "Flood Fill", another: false, sub: "Redo day. You read the solution, now write it again from a blank editor." });
    expect(dailyCopy(daily({ kind: "redo", why: "redo", due: 2 }))?.sub).toMatch(/One more is waiting after this one\.$/);
    const struggled = [slim({ redo_why: "effort" })], unsure = [slim({ redo_why: "shaky" })];
    expect(dailyCopy(daily({ kind: "redo", why: "redo", due: 1, items: struggled }))?.sub)
      .toBe("Redo day. You said it was a struggle, now write it again from a blank editor.");
    expect(dailyCopy(daily({ kind: "redo", why: "redo", due: 1, items: unsure }))?.sub)
      .toBe("Redo day. You were not sure you could repeat it, now write it again from a blank editor.");
    expect(dailyCopy(daily({ kind: "redo", why: "redo", due: 4 }))?.sub).toMatch(/3 more are waiting after this one\.$/);
    expect(dailyCopy(daily({ items: [] }))).toBeNull();
    expect(dailyCopy(undefined)).toBeNull();
  });
  it("numbers the hints that count and opens them in order", () => {
    const rung = (key: string, open: boolean) => ({ key, title: key, free: key === "clarify", open });
    const closed = ladderSteps([rung("clarify", false), rung("brute", false), rung("approach", false)]);
    expect(closed.map(r => [r.step, r.total, r.canOpen])).toEqual([[0, 2, true], [1, 2, true], [2, 2, false]]);
    expect(closed[0].copy.title).toBe("Ask the interviewer");
    const one = ladderSteps([rung("clarify", false), rung("brute", true), rung("approach", false)]);
    expect(one.map(r => r.canOpen)).toEqual([true, true, true]);
    const design = ladderSteps([rung("clarify", true), rung("growth", true), rung("boxes", false), rung("structure", false)]);
    expect(design.map(r => [r.step, r.total, r.canOpen])).toEqual([[0, 3, true], [1, 3, true], [2, 3, true], [3, 3, false]]);
    expect(ladderSteps([{ key: "mystery", title: "Custom", free: false, open: false }])[0].copy).toBeUndefined();
  });
});

describe("the debrief and the review queue", () => {
  it("writes times the way you would say them", () => {
    expect([0, 59, 60, 761, 3599, 3725].map(clockText)).toEqual(["0:00", "0:59", "1:00", "12:41", "59:59", "1:02:05"]);
    expect([20, 89, 1380, 3600, 3900, 7500].map(durationText))
      .toEqual(["under a minute", "1 minute", "23 minutes", "1 hour", "1 hour 5 minutes", "2 hours 5 minutes"]);
    expect(debriefHeadline({ solve_s: 1380, last_solve_s: 1380 })).toBe("Accepted in 23 minutes.");
    expect(debriefHeadline({ solve_s: 1380, last_solve_s: 240 })).toBe("Accepted in 4 minutes.");   // the latest solve, on a redo
    expect(debriefHeadline({ solve_s: null, last_solve_s: null })).toBe("Accepted.");
  });
  it("sums up the solve in one sentence", () => {
    expect(debriefFacts({ runs: 2, attempts: 1, hints: 0 })).toBe("2 runs, 1 submission and no hints.");
    expect(debriefFacts({ runs: 0, attempts: 3, hints: 1 })).toBe("3 submissions and 1 hint.");
    expect(debriefFacts({ runs: 1, attempts: 0, hints: 2 })).toBe("1 run, 1 submission and 2 hints.");
  });
  it("names the cards and asks a question for the ones without their own", () => {
    const card = (o: Partial<Card>): Card => ({ key: "k", kind: "dive", q: "", a: "", reps: 0, ivl: 0, due: null, ...o });
    expect(cardLabel("dive")).toBe("Follow-up");
    expect(cardLabel("edges")).toBe("Edge cases");
    expect(cardLabel("mystery")).toBe("Question");
    expect(cardQuestion(card({ kind: "dive", q: "Why not recursion?" }))).toBe("Why not recursion?");
    expect(cardQuestion(card({ kind: "complexity" }))).toBe("What are the time and space costs, and why?");
    const all = ["approach", "complexity", "dive", "followup", "edges", "design"].map(kind => card({ kind, key: kind }));
    expect(debriefCards(all).map(c => c.kind)).toEqual(["complexity", "dive", "followup"]);
    expect(debriefCards(undefined)).toEqual([]);
    expect([comesBack(1), comesBack(3), comesBack(16)]).toEqual(["Comes back tomorrow.", "Comes back in 3 days.", "Comes back in 16 days."]);
  });
  it("offers a review only when something is due", () => {
    expect(reviewCopy({ due: 0, problems: 0 })).toBeNull();
    expect(reviewCopy(undefined)).toBeNull();
    expect(reviewCopy({ due: 1, problems: 1 })).toEqual({ title: "1 question due", sub: "From one problem you solved. About 1 minute." });
    expect(reviewCopy({ due: 9, problems: 3 })).toEqual({ title: "9 questions due", sub: "From 3 problems you solved. About 5 minutes." });
  });
});

describe("mock rounds", () => {
  const mock = (o: Partial<Mock>): Mock => ({
    id: "1", corpus: "Amazon", format: "coding", minutes: 45, started_at: 1000, ends_at: 1000 + 45 * 60, ended_at: null,
    reason: "", active: false, solved: 0, total: 1, problems: [], ...o,
  });
  it("names the round and counts down by the server's clock", () => {
    expect(mockName(mock({}))).toBe("Amazon coding round");
    expect(mockName(mock({ corpus: "Google", format: "oa" }))).toBe("Google online assessment");
    expect(mockName(mock({ format: "other" }))).toBe("Amazon mock");
    expect([mockLeft(1600, 1000_000), mockLeft(1600, 1599_100), mockLeft(1600, 1700_000)]).toEqual([600, 1, 0]);
  });
  it("sums up how a mock ended", () => {
    expect(mockHeadline(mock({ reason: "done", solved: 1, ended_at: 1000 + 31 * 60 }))).toBe("Solved, with 14 minutes left.");
    expect(mockHeadline(mock({ reason: "done", solved: 1, ended_at: 1000 + 44 * 60 + 30 }))).toBe("Solved, right on the bell.");
    expect(mockHeadline(mock({ reason: "done", solved: 2, total: 2, minutes: 90, ended_at: 1000 + 70 * 60 }))).toBe("2 of 2 solved, with 20 minutes left.");
    expect(mockHeadline(mock({ reason: "time", ended_at: 1000 + 45 * 60 }))).toBe("Time ran out before it was solved.");
    expect(mockHeadline(mock({ reason: "time", solved: 1, total: 2, ended_at: 1000 + 90 * 60 }))).toBe("Time ran out. 1 of 2 solved.");
    expect(mockHeadline(mock({ reason: "ended", ended_at: 1000 + 12 * 60 }))).toBe("Ended after 12 minutes. 0 of 1 solved.");
    expect(mockHeadline(mock({ reason: "ended", ended_at: 1000 + 40 }))).toBe("Ended in the first minute. 0 of 1 solved.");
  });
  it("says what happened on each problem", () => {
    const p = { pid: "Amazon/X", id: "X", title: "t", ac_s: null, runs: 0, submits: 0 };
    expect(mockProblemLine({ ...p, ac_s: 1862, runs: 4, submits: 1 })).toBe("Accepted at 31:02, after 4 runs and 1 submission.");
    expect(mockProblemLine({ ...p, ac_s: 300, submits: 1 })).toBe("Accepted at 5:00, after 1 submission.");
    expect(mockProblemLine({ ...p, runs: 1, submits: 2 })).toBe("Not accepted, after 1 run and 2 submissions.");
    expect(mockProblemLine(p)).toBe("Not attempted.");
    expect(mockHistoryLine(mock({ reason: "done", solved: 1, ended_at: 1000 + 31 * 60 }))).toBe("1 of 1, in 31 minutes");
    expect(mockHistoryLine(mock({ reason: "time", solved: 1, total: 2 }))).toBe("1 of 2, time ran out");
    expect(mockHistoryLine(mock({ reason: "ended" }))).toBe("0 of 1, ended early");
  });
});

describe("the companion", () => {
  const pet = (o: Partial<Pet>): Pet => ({ egg: "jelly", name: "Awa", plan: "classics", hatched: false, to_hatch: 3, stage: 0, xp: 0, next_xp: null, mood: "egg", ...o });
  it("says what the egg needs before it hatches", () => {
    expect(petStatus(pet({}))).toBe("An egg. It hatches when you have solved three problems.");
    expect(petStatus(pet({ to_hatch: 2, xp: 30 }))).toBe("An egg. Two more solved problems and it hatches.");
    expect(petStatus(pet({ to_hatch: 1, xp: 60 }))).toBe("An egg. One more solved problem and it hatches.");
    expect([petCaption(pet({})), petCaption(pet({ to_hatch: 1 }))]).toEqual(["3 to hatch", "1 to hatch"]);
    expect(petProgress(pet({ to_hatch: 2 }), [200, 600])).toEqual({ value: 1 / 3, label: "1 of 3 solved" });
    expect(petLook(pet({ to_hatch: 1 }))).toEqual({ egg: "jelly", stage: 0, mood: "egg", cracks: 2 });
    expect(petMoodLine(pet({}), 4)).toBe("");
  });
  it("says how a hatched one is doing", () => {
    const young = pet({ hatched: true, to_hatch: 0, stage: 1, xp: 120, next_xp: 200, mood: "awake" });
    expect(petStatus(young)).toBe("A hatchling, with 120 XP. It grows at 200.");
    expect(petStatus(pet({ ...young, stage: 4, xp: 1600, next_xp: 3500 }))).toBe("An elder, with 1600 XP. It grows at 3500.");
    expect(petStatus(pet({ ...young, stage: 5, xp: 4000, next_xp: null }))).toBe("An ancient, with 4000 XP. It is fully grown.");
    expect(petProgress(young, [200, 600, 1500, 3500])).toEqual({ value: 0.6, label: "120 of 200 XP" });
    expect(petProgress(pet({ ...young, stage: 2, xp: 300, next_xp: 600 }), [200, 600, 1500, 3500])).toEqual({ value: 0.25, label: "300 of 600 XP" });
    expect(petProgress(pet({ ...young, stage: 5, xp: 4000, next_xp: null }), [200, 600, 1500, 3500])).toEqual({ value: 1, label: "4000 XP" });
    expect([petCaption(young), petCaption(pet({ ...young, mood: "hungry" })), petCaption(pet({ ...young, mood: "asleep" })), stageName(3), stageName(9)])
      .toEqual(["hatchling", "hungry", "asleep", "grown one", "ancient"]);
    expect(petMoodLine(young, 0)).toBe("It is awake and fed.");
    expect(petMoodLine(pet({ ...young, mood: "hungry" }), 1)).toBe("It is hungry: 1 question is due.");
    expect(petMoodLine(pet({ ...young, mood: "hungry" }), 6)).toBe("It is hungry: 6 questions are due.");
    expect(petMoodLine(pet({ ...young, mood: "asleep" }), 6)).toBe("It is asleep after 7 quiet days. A run, a submission or a review answer wakes it.");
    expect(petLook(young)).toEqual({ egg: "jelly", stage: 1, mood: "awake", cracks: 0 });
  });
  it("says what a solve paid, and why", () => {
    expect(xpLine("Awa", { xp: 30, pending: false, new_genre: true }, "graph")).toBe("Awa gets 30 XP, with the bonus for your first graph problem.");
    expect(xpLine("Awa", { xp: 24, pending: false, new_genre: false }, "graph")).toBe("Awa gets 24 XP.");
    expect(xpLine("Tsubo", { xp: 0, pending: true }, "tree")).toBe("Tsubo gets its XP when the redo is accepted.");
    const r = { pid: "p", id: "p", title: "t", genre: "graph", at: 1, xp: 1, size: 15, hints: 0, redos: 0, new_genre: false };
    expect([paidNote(r), paidNote({ ...r, new_genre: true, hints: 1 }), paidNote({ ...r, hints: 2, redos: 1 })])
      .toEqual(["", "first graph problem, 1 hint", "2 hints, 1 redo"]);
  });
});
