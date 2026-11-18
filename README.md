# mogi 模擬 — a personal serverless online judge

A single-user online judge for a local corpus of interview problems, built on AWS
serverless (CloudFront + S3 + API Gateway + two Lambdas + DynamoDB). Write code in
the browser, in **VS Code**, or in any editor via the **`mogi` CLI**; get an
AC/WA/RE/TLE/CE verdict in about a second; track progress by **genre** and
**importance**; and have every accepted solution committed to a GitHub repo
automatically.

Idle cost is effectively zero — there is no always-on compute anywhere in the stack.

## Why not Judge0 / DMOJ?

Those are multi-tenant, multi-language judges that need an always-on box with
privileged containers. This corpus is one user, one language (Python), and — the
key point — **the problems carry their own tests**. Every solution file in the
corpus follows one contract:

```python
# reference implementation (module body)
...
if __name__ == "__main__":
    # self-checking tests that print "N/N checks passed" and exit 0
```

So the judge doesn't need hand-written test cases at all. The ingester splits each
file with the `ast` module into *reference* and *harness*; judging a submission is:
append the problem's own harness to the user's code, run it in a sandbox, and read
the contract line. The reference implementation doubles as a hidden model answer
that unlocks after your first AC.

## Architecture

```
browser ──► CloudFront ──► S3 (static UI: Monaco editor, dashboard, heatmap)
VS Code ─┐     │
CLI ─────┴─ /api/* ──► HTTP API ──► api Lambda ──► DynamoDB (1 table)
   (Bearer token)                        │   ▲
                               async invoke   │ verdict
                                         ▼    │
                                      judge Lambda ──► subprocess sandbox
```

- **Auth** — GitHub OAuth with a one-login allowlist; the session is a stateless
  HS256 JWT in an HttpOnly cookie. The CLI and the VS Code extension hold the same
  kind of JWT as a long-lived Bearer token, obtained once through a browser hand-off
  (`/api/auth/cli` → `http://127.0.0.1:<port>/callback#token=…`; the token travels
  in the URL fragment so it never reaches a server log). No Cognito, no passwords.
- **Sandbox** — submissions run in a subprocess with a scrubbed environment (no
  AWS credentials are visible to submitted code), `python -I`, rlimits on
  memory/CPU/file size, and a wall-clock timeout. Verdicts: AC · WA (with the
  failing check's `got X want Y`) · RE · TLE · CE, each with "your code line N".
- **GitHub sync** — on an accepted submission the API commits the solution to a
  configured repo via the Contents API. By default it uses the OAuth token from
  login; set the `/mogi/sync-pat` SSM parameter to a fine-grained PAT
  (contents: read/write on that one repo) and login drops to `read:user` scope.
- **One host** — CloudFront serves the UI and proxies `/api/*` to API Gateway, so
  cookies are first-party and there is no CORS. A viewer-request CloudFront
  Function stashes the real host in `x-forwarded-host` for the OAuth redirect.
- **Spoiler discipline** — problem statements are split at ingest: the published
  statement and examples are always visible; the approach/complexity/hand-trace
  analysis, the reference implementation, and the test source unlock after AC.
  Before that, help comes in steps: hints one at a time, then the solution if you
  ask for it (see *Hints and the redo* below).
- **Problem ids are corpus-qualified** — `Amazon/A16`, `Google/C07`. The two
  corpora reuse bare ids (`C07` exists in both), and an earlier ingest silently let
  one overwrite the other. Every route, URL and local directory now carries the
  corpus; a bare id still works wherever it is unambiguous (`mogi open A16`).

## The web app (`web/`)

A Vite + React + TypeScript single-page app with one design system across three
routes, built mobile-first so it works as an iPhone home-screen app
(`manifest.webmanifest`, safe-area padding, 44 px targets, no input auto-zoom):

- `/` — **Home**: one glass card on the water. A one-sentence state of the campaign
  ("7 of 250 solved. Three-day streak. DP is 2 problems from done."), then **Today**:
  one problem sized for the time you likely have, with a "show another" link.
  Under it: **Continue** (the unsolved problem you touched most recently on any
  device, or the one this browser last had open if newer), **Highest ranked** (the
  most important open problem, whatever its size) and **All problems** — and a
  26-week heatmap. One call, `GET /api/home`; runs update `last_at`, so "working on
  it" counts before a submit.
- `/problems` — search, genre chips, sort, a filters sheet, group-by-genre with
  collapsible sections, tap-to-star, ✎ categorise. Rows become cards on phones.
- `/problem/<Corpus>/<id>` — split view on desktop (statement + required API |
  editor, verdicts, submissions); on phones a Statement / Code / Result segmented
  control with a bottom Run / Submit bar. The editor is CodeMirror 6, bundled
  (no CDN), Python-highlighted on the app's palette, ⌘↩ run / ⇧⌘↩ submit.

Old links keep working: `/problem.html?id=…` and `/problems.html` redirect.

The water is one WebGL fragment shader on a half-resolution canvas (drifting
colour bodies + a faint caustic shimmer), 30 fps on touch devices, paused when the
tab is hidden, a still frame under reduced motion. Everything else animates only
transforms and opacity (Motion springs for the sheet and segmented control), which
is what makes it smooth where the previous CSS-filter version stuttered. Glass is
`backdrop-filter` with a gradient rim and specular sheen.

```bash
cd web && npm ci
npm run dev        # http://localhost:5173 — /api is proxied to the judge's API with the CLI's token
npm test           # vitest: ranking, filters, grouping, copy
npm run build      # → web/dist (deployed by the CDK stack below)
```

## Genre, frequency, importance — and your own categorisation

Every problem carries metadata derived at ingest from the corpus front matter and
the corpus README, so the dashboard, the CLI and the VS Code tree can all sort and
group the same way:

| Field | Where it comes from |
|---|---|
| **genre** | the README's "Index by family" table (20 genres per corpus); falls back to the front-matter `Family` row. The two corpora name six families differently ("stack" and "stack/monotonic"); `GENRE_ALIASES` in the ingester folds each pair into one name, which leaves 25 genres |
| **freq** `2× · 11` | publications of this exact problem (Source + Alt source + † republished twin) · problems sharing the genre in the corpus |
| **rank** `#1…#7` | the Amazon README's "Start here" ranked shapes (the eleven Specification/Filter problems are rank 1) |
| **confidence** | ⭐ count in the front matter — how verbatim the published statement is |
| **importance** 0–100 | `45…15` for ranks 1–7 + `2 × min(genre size, 12)` + `8 × min(extra publications, 2)` + `4 × confidence` + `6 if Tier A` |

The dashboard has a **Sort** control (importance · frequency · genre · tier ·
recently worked · attempts · id — or click a column header), a **group by genre**
toggle with collapsible sections, a genre filter, and a **▶ Pick one** button that
opens the most important unsolved problem in the current filter.

The **✎ categorise** button on every row (and in the problem page header) opens a
popover where you set your own **genre** (override the corpus genre, or invent a
new one), **0–5 priority stars** and free-form **tags**. Stars outrank the computed
importance everywhere — a starred problem always sorts above an unstarred one — so
"what should I do next" is one click. The corpus genre is kept, so a reset is one
click too. The same data is editable from `mogi tag` and from the VS Code tree's
context menu.

## Difficulty, time, and Today

Every problem shows a difficulty and a rough time.
Both are derived at ingest, so there is nothing to maintain by hand.

| Field | Where it comes from |
|---|---|
| **difficulty** | the LeetCode twin's rating in the corpus `Practice` row. A long reference raises it, because an Easy twin is often a full design problem here. With no twin, the size of the reference decides, and the chip gets a dashed outline. |
| **minutes** `15 · 30 · 45 · 60+` | lines of real code in the reference (no blanks, comments or docstrings), scaled by the twin's rating. A rough guide. |

The list can filter by difficulty and sort **Easiest first** or **Shortest first**.

**Today** on the home page uses the time.
While you are starting out (fewer than 3 solved), or coming back after two weeks away, it offers the best 15-minute problem.
After that the budget grows to 30 minutes, then 45.
Inside the budget the order is the usual one: your stars first, then importance.
"Show another" walks through the next five candidates, and the choice is kept for the day.

## Hints and the redo

Each problem page has a **Hints** tab.
The steps come from the corpus's own analysis, so no hint was written by hand.

1. **Ask the interviewer** — the clarifying questions and the answers the tests assume. Free, because asking is what you do in the interview.
2. **Hints**, in order — brute force, then the approach in words. Design problems have three: what will change, the pieces, the design.
3. **The solution** — the analysis, the reference and the tests.

Hints are counted on your progress row. A later hint only opens after the one before it.

Reading the solution before an accepted submission marks the problem as assisted and sets a redo three days later.
Until then it rests: Today, Pick one and "next" skip it, and the list shows `redo in 3 days`.
On the redo day the solution closes again, the editor goes back to the starter stub, and Today asks for that problem first.
An accepted submission on or after that day clears the redo.
Peeking at the solution on the redo day starts the three days over.

## The debrief and the review queue

An accepted submission opens the **Debrief** tab instead of a toast.
It follows the order an interview does after the code works.

1. **How did it go?** "I could do it again" schedules nothing. "It was a struggle" brings the problem back in 7 days, "Not sure I could repeat it" in 3. Same redo as after reading the solution: blank editor, solution closed, Today asks for it first.
2. **Compare with the reference.** It opens next to your code, in the editor's colours.
3. **What the interviewer asks next.** The complexity, then the corpus's own follow-up questions, one at a time. Say the answer, show it, mark it "Knew it" or "Not yet".
4. **A note for next time.** One line you want to see again.

The problem page also shows a clock while you solve.
It counts in this browser while the tab is in front and you did something in the last five minutes.
The debrief opens with it: "Accepted in 23 minutes."

The questions are **cards**, built at ingest with nothing written by hand (2,220 in the two corpora):

| Card | Where it comes from |
|---|---|
| approach / design | the "Approach" section, or "Structure choice" on design problems |
| complexity | the cost bullets of "Complexity + dive-deeps", or the whole "Complexity" section |
| follow-up | every `- *"question"* → answer` bullet, and every row of a follow-up or escalation ladder |
| edge cases | the "Edge cases" table on design problems |

Cards come back on a schedule. "Knew it" climbs 3 → 7 → 16 → 35 → 90 days. "Not yet" comes back tomorrow.
A card you never answered is due 3 days after the solve.
When something is due, the home page shows a **Review** tile, and `/review` gives the cards one at a time, twelve to a sitting.
It is built for a phone. On a keyboard: space shows the answer, 1 is "Not yet", 2 is "Knew it".
On a redo day a problem's cards wait, because their answers would give the redo away.

## The companion

An optional layer over the same data. Pick an egg on `/companion`, and it lives in a round window on the home page.

- **Three eggs.** Awa (a glass drifter), Tsubo (a shell dweller) and Mosu (a kelp sprite). They are drawn in plain SVG by `web/src/components/Creature.tsx`.
- **Each egg comes with a path.** Classics (one problem per pattern, from a selection file), the Amazon corpus, or the Google corpus. While the path has open problems, Today and Highest ranked draw from it. The path can be changed at any time, to "Everything" too.
- **It hatches at three solved problems**, and what you solved before picking it already counts.
- **It grows with XP**, at 200, 600, 1500 and 3500.

| What you do | XP |
|---|---|
| Solve a problem | its size: 15, 30, 45 or 60 |
| Open a hint | a fifth off that problem, per hint |
| Solve your first problem in a genre | +15 |
| Read the solution | nothing until the redo is accepted, then the problem pays as usual |
| Finish a redo | +5 |
| Answer a review question | +1 |

It is hungry when review questions are due, and asleep after seven days with no run, submission or review answer.
Any of those wakes it. It never gets worse than asleep, and it loses nothing.

Only the choice is stored (one row: egg, path, name).
XP, stage and mood are worked out from your progress on every request, so they cannot drift.
Putting the companion away removes the window and nothing else.

`npm run dev` adds `/gallery`: every kind, stage and mood on one page, for working on the art. The build leaves it out.

The Classics path is optional, and it belongs to a corpus, so the selection is not in this repo.
The ingester reads `<root>/classics.json`, or `tools/classics.json` when the corpus has none (that file is ignored by git).
The order in the file is the order of the path.

```json
{ "parts": [
    { "title": "Part one",
      "problems": [ { "pid": "Corpus/ID", "pattern": "a pattern name" } ] } ] }
```

With no selection the Classics path is empty, and Today draws from every problem.

## Mock rounds

`/mock` runs a round the way an interview does: problems you have not solved, a clock, and no hints.

| Round | What is drawn | Default length |
|---|---|---|
| **Coding round** | one algorithm problem (Tier B, not tagged OA) | 45 minutes (or 30, 60) |
| **Design round** | one design-and-implement problem (Tier A, not tagged OA) | 60 minutes (or 45, 90) |
| **Online assessment** | two problems tagged OA, of different genres when it can | 90 minutes (or 60, 120) |

The draw is random among the dozen best-ranked problems you have never touched.
While a mock runs, its problem pages say nothing about genre, difficulty, time or sources, and the server refuses hints and the solution.
"Ask the interviewer" stays open, because that is allowed in an interview too.
Home leads with the mock and its countdown until it ends.

A mock ends when every problem is accepted, when the time is up, or when you end it.
The result says what was accepted and when, how many runs and submissions it took, and only then what kind of problem each one was.
A solved problem keeps its normal debrief. An unsolved one goes back to being a normal problem, hints and all.
Earlier mocks are listed on the mock page.

## Solve from VS Code

```bash
cd vscode && npm install && npm run package && code --install-extension mogi-0.1.0.vsix
```

Then click the ⚖ **mogi** icon in the activity bar → *Sign in with GitHub* (one
browser round-trip; the token is shared with the CLI). The tree is grouped by genre
and sorted by importance (change either from the view title). Clicking a problem
creates `~/mogi/<Corpus>/<slug>/solution.py` (from the stub, or from your accepted
solution) and opens the statement panel beside it. **Alt+R** runs the problem's
tests, **Alt+S** submits; the verdict renders LeetCode-style in the panel and the
failing line gets a red squiggle in the editor. Right-click → priority ★ / genre /
tags. **Alt+O** searches. See [`vscode/README.md`](vscode/README.md).

The web UI stays the primary surface; VS Code is an option per problem. Every
dashboard row has a **VS Code** chip and every problem page an **Open in VS Code**
button — both are `vscode://shiroyang.mogi/open?pid=…` links handled by the
extension's URI handler, which creates the local files and opens them. Progress,
priority, genre and tags are the same data wherever you look.

Web assets are deployed with `Cache-Control: no-cache` and the HTML references
`/mogi.js?v=<content hash>`, so a browser can never pair a new page with a script
it cached earlier.

## Solve from the terminal (any editor)

```bash
python3 -m pip install --user -e cli        # → ~/.local/bin/mogi
mogi login                                  # browser hand-off, token → ~/.config/mogi/config.json
mogi ls --sort importance -n 20             # or --sort easiest --difficulty easy --genre graph --status fresh --tag redo --json
mogi open A16 --code                        # ~/mogi/Amazon/A16_…/{problem.md, solution.py}; opens VS Code
mogi run                                    # in that directory: the problem's own tests, does not count
mogi submit                                 # counts: AC unlocks spoilers and syncs to GitHub
mogi tag A16 --priority 5 --add-tag redo    # categorise; --genre graph / --reset-genre
mogi pick --genre allocation --open         # the most important unsolved one
mogi stats · mogi web A16 · mogi whoami
```

Exit codes: 0 = AC, 1 = any other verdict, 2 = error — so `mogi run && git commit`
style chaining works. `mogi run` / `mogi submit` find the problem from the nearest
`.mogi.json`, so they work from inside the problem directory, or take an id/path.

## Deploy

```bash
(cd web && npm ci && npm run build)                           # the stack deploys web/dist
cd infra
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
npx -y aws-cdk@latest bootstrap aws://<account>/<region>   # once
npx -y aws-cdk@latest deploy
```

A CloudFront Function serves `index.html` for any extensionless path, so the SPA's
routes work on reload; the API behaviour is untouched (custom error responses would
have rewritten its JSON errors too).

**The front door is Vercel: https://mogi-judge.vercel.app.** `web/vercel.json`
rewrites `/api/*` to the API Gateway URL (same-origin, so cookies keep working) and
everything else falls back to `index.html`; Vercel forwards the original host, so
the API builds the OAuth redirect for the Vercel origin by itself (the SSM parameter
`/mogi/site-origin` can pin it if a front door ever doesn't). The GitHub OAuth app's
callback URL is `https://mogi-judge.vercel.app/api/auth/callback`. Deploy the UI with
`cd web && npx vercel deploy --prod` (or connect the GitHub repo in the Vercel
dashboard with root directory `web` for deploys on push). The CloudFront
distribution still serves the same build as a fallback, but only one origin can
own the GitHub login at a time.

Edit the constants at the top of `infra/app.py` first (account, region, GitHub
login, sync repo). Every resource is tagged `auto-delete: no` and `project: mogi`.

Then create a GitHub OAuth app (github.com → Settings → Developer settings →
OAuth Apps → New):

- Homepage URL: the `SiteURL` stack output
- Authorization callback URL: the `OAuthCallbackURL` stack output

and store its credentials:

```bash
aws ssm put-parameter --name /mogi/github/client-id     --type String       --value <client_id>
aws ssm put-parameter --name /mogi/github/client-secret --type SecureString --value <client_secret>
```

Finally, ingest a corpus (any directory tree following the contract above —
`<root>/<Corpus>/problems/*.md` + `<root>/<Corpus>/solutions/*.py`, plus an
optional `<root>/<Corpus>/README.md` with an "Index by family" table for genres,
and an optional `<root>/classics.json` for the Classics path):

```bash
python3 tools/ingest.py /path/to/corpus --table mogi --region <region> --prune-stale
python3 tools/ingest.py /path/to/corpus --dry-run --show Amazon/A16   # parse + report only
```

The ingester re-verifies every reference solution through the actual judge before
uploading — if a problem's own reference can't get AC, nothing is written.
`--prune-stale` removes problem rows that are no longer in the corpus (including
the old bare-id rows); `tools/migrate_ids.py --apply` moves per-user progress and
submission rows from bare ids to corpus-qualified ones.

`tools/mirror_problems.py <corpus> --repo <owner>/<repo>` mirrors into the solutions
repo (github.com/shiroyang/mogi-solutions, private — the judge's OAuth token carries
the `repo` scope), next to the judge's accepted-solution file `<Corpus>/<slug>.py`:
`<Corpus>/<slug>.md`, the spoiler-free question, and `<Corpus>/<slug>.reference.md`,
the reference solution — the corpus's own analysis regrouped as *how it's solved*,
*the core code explained*, hand-trace, edge cases, complexity, production notes and
the follow-up ladder, then the complete clean implementation and the tests the judge
runs. It also regenerates the README as an index sorted by importance with ✅ on
accepted problems. The judge's sync target is the SSM parameter `/mogi/sync-repo`.

## Run it on this machine

`tools/devapi.py` serves the real API handlers and the real judge from memory, loaded with the corpus.
Nothing in it talks to AWS or GitHub, and you are signed in as a local user.

```bash
python3 tools/devapi.py /path/to/corpus --solved Amazon/B01      # http://127.0.0.1:8787
cd web && MOGI_SITE=http://127.0.0.1:8787 MOGI_CONFIG=/dev/null npm run dev
curl -X POST 'http://127.0.0.1:8787/dev/clock?days=3'            # three days later: a redo or a review comes due
curl 'http://127.0.0.1:8787/dev/reference?pid=Amazon/B36'        # a reference solution, to try an accepted solve
```

State is gone when the server stops, so it is a safe place to click everything.

## Verification

`tools/corpus_sweep.py` submits every reference implementation to the judge as if
it were user code and requires 250/250 AC, plus sabotage cases proving each
verdict fires (wrong answer, crash, infinite loop, syntax error).
`python3 -m unittest discover -s cli/tests` covers the CLI offline (rendering,
workspace layout, id resolution, config); `cd vscode && npm run typecheck`.

`python3 -m unittest discover -s tests` runs the API and the judge's progress updates
against `tools/fakeddb.py`, an in-memory table that refuses what DynamoDB refuses:
a reserved word used bare, an unused or undefined placeholder, overlapping paths, a float.
It covers the hint ladder, the redo, the Today pick, the debrief, the cards and their schedule, mock rounds, the companion, and what the ingester derives.

## Layout

```
backend/judge/   splitter.py (ast split, stub generation) · runner.py (sandbox) · handler.py
backend/api/     handler.py (routes, OAuth + Bearer, JWT, meta, GitHub sync — stdlib + boto3 only)
web/             Vite + React app: src/pages (Home, Problems, Problem, Review, Mock, Companion, Login) · src/components (Water shader, Sheet, Categorise, Editor, Hints, Debrief, Cards, Creature, SolveClock, MockClock, Verdict, ui) · src/model.ts (+tests) · vercel.json · legacy/ (the pre-React pages)
cli/             mogi_cli/ (stdlib-only `mogi` command) · tests/
vscode/          the VS Code extension (TypeScript, esbuild-bundled, no runtime deps)
infra/           app.py (CDK, one stack)
tools/           ingest.py · migrate_ids.py · mirror_problems.py · corpus_sweep.py · devapi.py (local API) · localbackend.py · fakeddb.py
tests/           API, judge progress, ingester and fake-table tests
```
