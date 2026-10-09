# mogi for VS Code

Solve the 真題 corpus without leaving the editor.

- **Problems view** (activity bar ⚖): grouped by genre / tier / corpus / status, sorted by
  importance (your ★ priority first, then the computed score), frequency, id, or recency.
- Click a problem → `solution.py` opens on the left, the statement panel on the right
  (statement, required API, starter stub, source + practice links, "next in genre").
- **Alt+R** runs the problem's own tests, **Alt+S** submits. The verdict lands in the panel
  LeetCode-style (case chips, input / output / expected, where it failed) and the failing
  line gets a red squiggle in `solution.py`.
- Right-click a problem → set **priority ★**, **genre**, **tags**. Same data as the web UI.
- **Alt+O** searches problems; status bar shows solved / total.

Files live in `~/mogi/<Corpus>/<slug>/` — the same layout the `mogi` CLI uses, and the
sign-in token is shared through `~/.config/mogi/config.json`.

## Build

```bash
cd vscode
npm install
npm run package            # typecheck → bundle → mogi-0.1.0.vsix
code --install-extension mogi-0.1.0.vsix
```
