# mogi-cli

Command-line client for [mogi](https://github.com/shiroyang/mogi), the 真題 online judge.
Stdlib only; Python ≥ 3.10.

```bash
python3 -m pip install --user -e .    # → ~/.local/bin/mogi
mogi login                            # one browser round-trip; token in ~/.config/mogi/config.json
mogi ls -n 20                         # sorted by importance (your ★ first), --genre/--status/--tag/-q filters
mogi open A16 --code                  # ~/mogi/Amazon/A16_…/{problem.md, solution.py}
mogi run                              # judge solution.py against the problem's own tests
mogi submit                           # counts; AC unlocks spoilers and syncs to GitHub
mogi tag A16 --priority 5 --add-tag redo
mogi pick --open · mogi stats · mogi web A16
```

Exit codes: 0 = AC / success, 1 = any other verdict, 2 = error.
The config file (`site`, `token`, `workspace`) is shared with the VS Code extension;
`MOGI_CONFIG=/path/to/config.json` overrides its location.
