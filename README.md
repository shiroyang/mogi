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
- **Problem ids are corpus-qualified** — `Amazon/A16`, `Google/C07`. The two
  corpora reuse bare ids (`C07` exists in both), and an earlier ingest silently let
  one overwrite the other. Every route, URL and local directory now carries the
  corpus; a bare id still works wherever it is unambiguous (`mogi open A16`).

## The web app (`web/`)

A Vite + React + TypeScript single-page app with one design system across three
routes, built mobile-first so it works as an iPhone home-screen app
(`manifest.webmanifest`, safe-area padding, 44 px targets, no input auto-zoom):

- `/` — **Home**: one glass card on the water. A one-sentence state of the campaign
  ("7 of 250 solved. Three-day streak. DP is 2 problems from done."), then exactly
  three actions — **Continue** (the unsolved problem you touched most recently on
  any device, or the one this browser last had open if newer), **Next up**
  (highest-ranked unsolved), **All problems** — and a 26-week heatmap. One call,
  `GET /api/home`; runs update `last_at`, so "working on it" counts before a submit.
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
npm run dev        # http://localhost:5173 — /api is proxied to the judge with the CLI's token
npm test           # vitest: ranking, filters, grouping, copy
npm run build      # → web/dist (deployed by the CDK stack below)
```

## Genre, frequency, importance — and your own categorisation

Every problem carries metadata derived at ingest from the corpus front matter and
the corpus README, so the dashboard, the CLI and the VS Code tree can all sort and
group the same way:

| Field | Where it comes from |
|---|---|
| **genre** | the README's "Index by family" table (20 genres per corpus); falls back to the front-matter `Family` row |
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
mogi ls --sort importance -n 20             # or --genre graph --status fresh --tag redo --json
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

**Hosting the UI elsewhere.** `web/vercel.json` makes the same build deployable on
Vercel: `/api/*` is rewritten to the API Gateway URL (same-origin, so cookies keep
working) and everything else falls back to `index.html`. Two one-time steps when
switching front doors: set the SSM parameter `/mogi/site-origin` to the new origin
(the OAuth redirect is built from it), and change the GitHub OAuth app's callback
URL to `<new origin>/api/auth/callback`. A custom domain on CloudFront works the
same way (ACM certificate in us-east-1 + alias), without the Vercel hop.

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
optional `<root>/<Corpus>/README.md` with an "Index by family" table for genres):

```bash
python3 tools/ingest.py /path/to/corpus --table mogi --region <region> --prune-stale
python3 tools/ingest.py /path/to/corpus --dry-run --show Amazon/A16   # parse + report only
```

The ingester re-verifies every reference solution through the actual judge before
uploading — if a problem's own reference can't get AC, nothing is written.
`--prune-stale` removes problem rows that are no longer in the corpus (including
the old bare-id rows); `tools/migrate_ids.py --apply` moves per-user progress and
submission rows from bare ids to corpus-qualified ones.

`tools/mirror_problems.py <corpus> --repo <owner>/<repo>` mirrors every question
(statement, required API, stub, links — no spoilers) into the solutions repo as
`<Corpus>/<slug>.md` next to the judge's `<Corpus>/<slug>.py`, and regenerates its
README as an index sorted by importance with ✅ on accepted problems. The repo can
be private: the judge's OAuth token carries the `repo` scope.

## Verification

`tools/corpus_sweep.py` submits every reference implementation to the judge as if
it were user code and requires 250/250 AC, plus sabotage cases proving each
verdict fires (wrong answer, crash, infinite loop, syntax error).
`python3 -m unittest discover -s cli/tests` covers the CLI offline (rendering,
workspace layout, id resolution, config); `cd vscode && npm run typecheck`.

## Layout

```
backend/judge/   splitter.py (ast split, stub generation) · runner.py (sandbox) · handler.py
backend/api/     handler.py (routes, OAuth + Bearer, JWT, meta, GitHub sync — stdlib + boto3 only)
web/             Vite + React app: src/pages (Home, Problems, Problem, Login) · src/components (Water shader, Sheet, Categorise, Editor, Verdict, ui) · src/model.ts (+tests) · vercel.json · legacy/ (the pre-React pages)
cli/             mogi_cli/ (stdlib-only `mogi` command) · tests/
vscode/          the VS Code extension (TypeScript, esbuild-bundled, no runtime deps)
infra/           app.py (CDK, one stack)
tools/           ingest.py · migrate_ids.py · mirror_problems.py · corpus_sweep.py
```
