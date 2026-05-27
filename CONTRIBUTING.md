# Contributing to ZunZunNG

This guide is for contributors changing the code. For end-user install / "what does this do", see [`README.md`](README.md).

## Quick start

```bash
uv sync                                   # one-time: create .venv, install deps
uv run python manage.py migrate           # one-time: creates the django_session table
uv run python manage.py runserver         # open http://127.0.0.1:8000/
```

`.venv/` must be excluded from cloud-sync clients (Dropbox/OneDrive/iCloud) — see [`docs/internals/active-gotchas.md`](docs/internals/active-gotchas.md) § Environment and venv for why and the `UV_LINK_MODE=copy` workaround if you can't exclude it.

## Running tests

Two layers:

```bash
uv run pytest tests/ -v                   # ~20 s, no server required
uv run python scripts/smoke_test.py       # ~1–5 min, exercises the full fit flow
```

CI (`.github/workflows/ci.yml`) runs pytest on Linux/macOS/Windows and smoke on Linux for every push, every PR, and weekly. Local pytest covers `platform_compat`, `ChildPayload` round-trip, pickle-safety of every LRP subclass, URL routing, view rendering, and session round-trip.

The first smoke run after `rm -rf .venv && uv sync` can time out on 3D scenarios because spawn workers compile `.pyc` files on first import — re-running on the warm venv passes. See [`docs/internals/active-gotchas.md`](docs/internals/active-gotchas.md) § Environment and venv.

## Git workflow

### Feature branches with `--no-ff` merges

Every non-trivial change goes through a feature branch and merges to `main` with `--no-ff`, preserving topology in `git log --first-parent`. Recent merge commits on `main` are templates for the structure (rationale, scope, verification, references to specs/plans if any).

Merge commit subject convention: `Merge feat/<branch>` (or `Merge fix/<branch>`, etc.).

### Commit messages — Conventional Commits

Subjects follow the `type(scope): subject` shape, with `scope` optional. Allowed types are encoded in [`cchk.toml`](cchk.toml) (single source of truth) and validated on every PR by [`.github/workflows/commit-check.yml`](.github/workflows/commit-check.yml).

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.

Examples from recent history:

```
feat(views): split parallelProcessCount out, switch card to .notice
fix(histogram): unique 3-char anchors h00..h2r, drop xsh+rank scheme
refactor: compact artifact filenames (base36 unique + 3-letter anchors)
style(pdf): move page-footer text 0.5 inch closer to the bottom
docs: extract operational gotchas to docs/internals/active-gotchas.md
```

Subject limit: 5–72 chars. Imperative-mood and capitalization checks are off (false-positive prone in the upstream tool); reviewer judgment fills that gap.

### Branch naming — Conventional Branch

Branch names start with one of: `feature/`, `bugfix/`, `hotfix/`, `release/`, `chore/`, `feat/`, `fix/`. Also encoded in [`cchk.toml`](cchk.toml) and validated on every PR.

Bot-opened PRs (Dependabot, Renovate) skip the branch check because their branch names (`dependabot/...`) don't match the allow-list — the workflow filters them via `pull_request.user.login`.

## Opening a pull request

1. Push your feature branch to `origin`.
2. Open the PR via the GitHub UI or `gh pr create` from your terminal.
3. [`.github/workflows/claude-code-review.yml`](.github/workflows/claude-code-review.yml) will auto-run a multi-agent code review on every PR (open / sync / ready_for_review / reopened) from human authors and post findings as a PR comment. Bot PRs are skipped.
4. Address Critical findings; push fixups; the auto-review re-runs on each sync.

For the auto-review to actually run, the repo secret `CLAUDE_CODE_OAUTH_TOKEN` must be set (Settings → Secrets and variables → Actions). Without it the first step fails with a clear error and no review is posted; nothing else breaks.

You can also `@claude` mention in any PR comment, PR review, or issue body to ask Claude to do specific work in-thread — handled by [`.github/workflows/claude.yml`](.github/workflows/claude.yml). Same secret required.

### Agent contributors: PR-creation gate

If you use Claude Code (or another agent that issues Bash tool calls) to open PRs, you can install a per-developer PreToolUse hook that denies `gh pr create` unless a per-HEAD code-review marker exists. The hook script and `.claude/settings.json` snippet are not in the repo (the `.claude/` directory is gitignored — agent infra is per-developer). Set up locally if desired; for canonical-content reference see the dbxignore project's [`.claude/settings.json`](https://github.com/kiloscheffer/dbxignore/blob/main/.claude/settings.json).

## Optional: pre-commit hooks

[`.pre-commit-config.yaml`](.pre-commit-config.yaml) provides two opt-in local hook families:

- **commit-check** — validates Conventional Commits message and Conventional Branch name against `cchk.toml`. Runs at `commit-msg` and `pre-push` time.
- **mypy** — project-wide type check at `pre-commit` time.

Install once per clone:

```bash
uv tool install pre-commit
pre-commit install --hook-type commit-msg --hook-type pre-push
```

If you get *"Cowardly refusing to install hooks with `core.hooksPath` set"*, run `git config --local --unset core.hooksPath` first. The check guards against conflicting hook managers like Husky; on a clean clone it's usually a redundant default-value setting.

CI re-runs the equivalent checks via [`.github/workflows/commit-check.yml`](.github/workflows/commit-check.yml) and [`.github/workflows/ci.yml`](.github/workflows/ci.yml), so the local install is a convenience, not a merge gate.

Ruff is deliberately not configured — see the comment in `.pre-commit-config.yaml` if you want to revisit that decision.

## Before touching code

[`docs/internals/active-gotchas.md`](docs/internals/active-gotchas.md) holds operational rules-of-thumb grouped by code area: spawn LRP pattern, sessions & state, templates & URLs, files & directories, filename grammar in `temp/`, FunkLoad legacy, deploy. Scan the matching section before editing — each bullet captures one tripping-hazard that has burned someone before.

## Other docs

- [`docs/deployment/{linux,macos,windows}.md`](docs/deployment/) — per-platform deploy recipes (systemd unit, launchd plist, IIS + NSSM).
- [`docs/operations/quarterly-upgrade.md`](docs/operations/quarterly-upgrade.md) — the recurring dependency-upgrade procedure that *moves* `uv.lock`. CI never moves the lock; it only verifies.
- [`BACKLOG.md`](BACKLOG.md) — open work items and RESOLVED entries that capture historical scope decisions.
