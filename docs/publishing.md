# Releasing Serpentine to PyPI — owner walkthrough

Everything mechanical is done: `dist/` contains twine-checked artifacts for both
packages (`serpentine-shim 0.3.0`, `serpentine-lang 0.4.0`). The only missing inputs
are **your PyPI credentials**. This is the complete path from zero to published.

## 1. Where the credentials come from

1. **Create a PyPI account**: https://pypi.org/account/register/ (one account owns both
   packages). Enable 2FA when prompted — PyPI requires it for new uploads.
2. **Create an API token**: https://pypi.org/manage/account/token/ →
   "Add API token" → scope **"Entire account"** for the *first* upload (the projects
   don't exist yet, so project-scoped tokens can't be created until after).
   The token looks like `pypi-AgEIcHlwaS5vcmc...` — copy it immediately; it is shown once.
3. **After the first upload**, revoke that token and mint two **project-scoped** tokens
   (one per package) for future releases. Never reuse the account-wide token.
4. Optional dry-run: register at https://test.pypi.org (separate account + token) and
   upload there first with `--repository testpypi`.

## 2. Upload (either of us can run this)

```powershell
# from the repo root, venv active — dist\ already contains the checked artifacts
.venv\Scripts\python.exe -m twine check dist/*          # already PASSED, re-run for comfort
.venv\Scripts\python.exe -m twine upload dist/*
#   username: __token__
#   password: pypi-AgEI...   (the API token)
```

Non-interactive alternative (what I would run if you hand me a token):

```powershell
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "pypi-AgEI..."      # your token
.venv\Scripts\python.exe -m twine upload dist/*
```

> Security note: prefer pasting the token into the interactive prompt or a CI secret
> over putting it in chat or shell history. If you do share it with me, revoke it right
> after the upload and replace it with project-scoped tokens.

## 3. Verify

```powershell
python -m pip install --no-cache-dir serpentine-shim serpentine-lang
serp check examples\json_parser.py
python -m pip index versions serpentine-lang
```

Both package names were verified unregistered (2026-07-17); first upload claims them.

## 4. Follow-ups after the first upload

- **GitHub org / repo naming** (Phase-0 box): optional; the repo can stay where it is —
  update `pyproject.toml` `[project.urls]` if it moves.
- **Trusted publishing (recommended)**: on PyPI, add a "trusted publisher" for the GitHub
  repo + a `release.yml` workflow — future releases then publish from CI on tag push with
  **no long-lived tokens at all**. I can write that workflow when you want it.
- **Announce**: the release notes write themselves from `CHECKLIST.md` + `docs/tour.md`
  ("a Python subset that compiles to 140 KB native binaries with a borrow checker —
  same file runs under CPython"). Typical venues: r/ProgrammingLanguages, Hacker News
  (Show HN), lobste.rs, the Python Discourse #show-and-tell.

## Release checklist (for every future version)

1. Bump `compiler/pyproject.toml` and/or `shim/pyproject.toml` (+ `serpentine/__init__.py.__version__`).
2. Full battery: `run_differential_tests`, `run_reject_serp`, `run_rustc_agreement`,
   `run_llvm_differential`, `run_lsp_smoke` — all green, CI green.
3. `python -m build --outdir dist shim` / `... compiler`; `twine check dist/*`.
4. `twine upload dist/*` (project-scoped tokens), tag the commit `vX.Y.Z`.
