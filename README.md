# mogi 模擬 — a personal serverless online judge

A single-user online judge for a local corpus of interview problems, built on AWS
serverless (CloudFront + S3 + API Gateway + two Lambdas + DynamoDB). Write code in
the browser, get an AC/WA/RE/TLE/CE verdict in about a second, track progress, and
have every accepted solution committed to a GitHub repo automatically.

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
               │
               └─ /api/* ──► HTTP API ──► api Lambda ──► DynamoDB (1 table)
                                             │   ▲
                                   async invoke   │ verdict
                                             ▼    │
                                          judge Lambda ──► subprocess sandbox
```

- **Auth** — GitHub OAuth with a one-login allowlist; the session is a stateless
  HS256 JWT in an HttpOnly cookie. No Cognito, no user pool, no passwords.
- **Sandbox** — submissions run in a subprocess with a scrubbed environment (no
  AWS credentials are visible to submitted code), `python -I`, rlimits on
  memory/CPU/file size, and a wall-clock timeout. Verdicts: AC · WA (with the
  failing check's `got X want Y`) · RE · TLE · CE.
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

## Deploy

```bash
cd infra
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
npx -y aws-cdk@latest bootstrap aws://<account>/<region>   # once
npx -y aws-cdk@latest deploy
```

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
`<root>/<Corpus>/problems/*.md` + `<root>/<Corpus>/solutions/*.py`):

```bash
python3 tools/ingest.py /path/to/corpus --table mogi --region <region>
```

The ingester re-verifies every reference solution through the actual judge before
uploading — if a problem's own reference can't get AC, nothing is written.

## Verification

`tools/corpus_sweep.py` submits every reference implementation to the judge as if
it were user code and requires 250/250 AC, plus sabotage cases proving each
verdict fires (wrong answer, crash, infinite loop, syntax error).

## Layout

```
backend/judge/   splitter.py (ast split, stub generation) · runner.py (sandbox) · handler.py
backend/api/     handler.py (routes, OAuth, JWT, GitHub sync — stdlib + boto3 only)
web/             index.html (dashboard + heatmap) · problem.html (Monaco + verdicts) · css/js
infra/           app.py (CDK, one stack)
tools/           ingest.py · corpus_sweep.py
```
