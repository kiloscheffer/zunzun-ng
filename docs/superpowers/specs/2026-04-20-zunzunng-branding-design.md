# ZunZunNG branding: user-visible string rebrand

**Date:** 2026-04-20
**Closes TODO entry:** "Complete ZunZunNG rebrand in user-facing strings" (added 2026-04-20 as part of the top-level rebrand commit `a43034c`).

## Context

The top-level project identity was renamed from `zunzunsite3` to `zunzunng` (ZunZunNG, "Next Generation") in commit `a43034c` (2026-04-20) and the code was pushed to the private repo `github.com/kiloscheffer/zunzunng` at tag `v1.0.0-ng`. That commit touched only the identity surface: `pyproject.toml`, `uv.lock`, `CLAUDE.md`, `README.txt`, `CHANGELOG`, plus a new `TODO.md` entry flagging the remaining user-visible strings as a follow-up.

This spec captures that follow-up: approximately 25 `ZunZunSite3` / `zunzunsite3` / bitbucket-URL occurrences across ~15 files in `templates/` and `zunzun/`, plus a two-section rewrite of `templates/zunzun/divs/about.html` that preserves James R. Phillips's original attribution verbatim while introducing a ZunZunNG section.

## Goals

- Every user-visible `ZunZunSite3` string in rendered HTML, PDF watermarks, and graph watermarks displays as `ZunZunNG` (mixed case) or `zunzunng` (lowercase watermarks/logs) after the change.
- Every URL pointing at the dormant upstream `bitbucket.org/zunzuncode/zunzunsite3` points at the fork's home `github.com/kiloscheffer/zunzunng`.
- The legacy Google-group URL is replaced with the active FindCurves group.
- `templates/zunzun/divs/about.html` satisfies BSD-2-clause attribution by preserving Phillips's prose verbatim while making the ZunZunNG fork's identity explicit.
- `pytest tests/ -v` (78/78) and `scripts/smoke_test.py` (12/12) both pass unchanged before and after.

## Non-goals

- Renaming the `zunzun/` Django app folder. Pure internal path; renaming would churn ~every import/template reference across the codebase for zero user value.
- Renaming the filesystem working directory (`C:\Dropbox\git\zunzunsite3`). Affects Dropbox sync, `.venv` paths, existing auto-memory entries. Separate decision outside this branch.
- Rewriting historical `docs/superpowers/specs/*.md` or `docs/superpowers/plans/*.md` files. Those documents describe work done on the project under its prior name; rewriting them would falsify the historical record.
- Touching already-closed `TODO.md` entries (the four RESOLVED sections). They name "zunzunsite3" accurately for the time period they describe.
- Touching `DEDICATION.txt` (Phillips's personal religious dedication).
- Touching `LICENSE.txt` (BSD-2-clause copyright notice — load-bearing per clause 1 of the license).

## Scope: enumerated hit sites

Enumerated via `grep -ri 'zunzunsite3\|ZunZunSite3' templates/ zunzun/ scripts/` on 2026-04-20 against commit `a43034c`:

### Templates (10 files)

| File | Hit | Substitution |
|------|-----|-------------|
| `templates/zunzun/home_page.html:91` | `Welcome to ZunZunSite3` header | → `Welcome to ZunZunNG` |
| `templates/zunzun/home_page.html:97` | Bitbucket link `<a href="https://bitbucket.org/zunzuncode/zunzunsite3">` | → `<a href="https://github.com/kiloscheffer/zunzunng">` |
| `templates/zunzun/home_page.html:149` | Google-group icon `alt="ZunZunSite3 Google Group"` + URL `http://groups.google.com/group/zunzun_dot_com/` | → `alt="FindCurves Google Group"` + `https://groups.google.com/g/findcurves` |
| `templates/zunzun/home_page.html:156` | `ZunZunSite3's Google discussion group` link text + same URL | → `FindCurves Google discussion group` + `https://groups.google.com/g/findcurves` |
| `templates/zunzun/divs/about.html` (entire file, 10 lines) | Two-section rewrite — see §"about.html rewrite" below | Preserve Phillips's prose verbatim; prepend NG section |
| `templates/zunzun/divs/feedback_entry.html:7` | `try the ZunZunSite3 <a href='http://groups.google.com/group/zunzun_dot_com/'>Google discussion group</a>` | → `try the FindCurves <a href='https://groups.google.com/g/findcurves'>Google discussion group</a>` |
| `templates/zunzun/feedback_reply.html:10` | `return to ZunZunSite3` | → `return to ZunZunNG` |
| `templates/zunzun/function_finder_interface.html:4` | Title `ZunZunSite3 - {{ dimensionality }}D Function Finder` | → `ZunZunNG - {{ dimensionality }}D Function Finder` |
| `templates/zunzun/function_finder_interface.html:50` | Bitbucket Home link | → `https://github.com/kiloscheffer/zunzunng` |
| `templates/zunzun/function_finder_results.html:4` | Title `ZunZunSite3 - {{ dimensionality }}D Function Finder Results` | → `ZunZunNG` prefix |
| `templates/zunzun/generic_error.html:4` | Title `ZunZunSite3 Curve Fitting and Surface Fitting` | → `ZunZunNG` prefix |
| `templates/zunzun/generic_page_template.html:118` | Bitbucket "Django (this site)" link | → github URL |
| `templates/zunzun/invalid_form_data.html:4` | Title prefix | → `ZunZunNG` |
| `templates/zunzun/list_all_equations.html:4` | Title prefix | → `ZunZunNG` |

### Views (1 file)

| File:Line | Hit | Substitution |
|-----------|-----|-------------|
| `zunzun/views.py:261` | `"...delete the zunzunsite3 browser cookie..."` (user-visible HTTP response body) | → `ZunZunNG browser cookie` (mixed case — user-visible) |
| `zunzun/views.py:513` | `EmailMessage('ZunZunSite3 Feedback Form', ...)` (email subject) | → `'ZunZunNG Feedback Form'` |
| `zunzun/views.py:549` | `items_to_render['header_text'] = 'ZunZunSite3 Online Curve Fitting<br>and Surface Fitting Web Site'` | → `'ZunZunNG ...'` |
| `zunzun/views.py:576` | `header_text = 'ZunZunSite3 List Of All ' + ...` | → `'ZunZunNG List Of All '` |
| `zunzun/views.py:578` | `header_text = 'ZunZunSite3 List Of All Standard ' + ...` | → `'ZunZunNG List Of All Standard '` |

### LRP subclasses (4 files)

| File:Line | Hit | Substitution |
|-----------|-----|-------------|
| `zunzun/LongRunningProcess/FittingBaseClass.py:189` | `title_string = 'ZunZunSite3 - ' + ...` | → `'ZunZunNG - '` |
| `zunzun/LongRunningProcess/FunctionFinder.py:565` | `header_text = 'ZunZunSite3 ' + str(self.dimensionality) + 'D Function Finder Interface'` | → `'ZunZunNG '` |
| `zunzun/LongRunningProcess/FunctionFinder.py:566` | `title_string` (same substring) | → `'ZunZunNG '` |
| `zunzun/LongRunningProcess/FunctionFinderResults.py:113` | `header_text = 'ZunZunSite3<br>' + ...` | → `'ZunZunNG<br>'` |
| `zunzun/LongRunningProcess/FunctionFinderResults.py:114` | `title_string` (same) | → `'ZunZunNG '` |
| `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py:128` | PDF watermark URL `https://bitbucket.org/zunzuncode/zunzunsite3` | → `https://github.com/kiloscheffer/zunzunng` |
| `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py:269` | PDF credit string `'ZunZunSite3'` | → `'ZunZunNG'` |
| `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py:825` | `header_text = 'ZunZunSite3<br>' + self.webFormName` | → `'ZunZunNG<br>'` |
| `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py:826` | `title_string = 'ZunZunSite3 ' + ...` | → `'ZunZunNG '` |
| `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py:884` | `header_text = 'ZunZunSite3 ' + str(self.dimensionality) + 'D Interface<br>' + ...` | → `'ZunZunNG '` |
| `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py:885` | `title_string = 'ZunZunSite3 ' + ...` | → `'ZunZunNG '` |

### Graph + log + docstring (3 files)

| File:Line | Hit | Substitution |
|-----------|-----|-------------|
| `zunzun/LongRunningProcess/MatplotlibGraphs_2D.py:94` | `ax.text(..., 'zunzunsite3', ...)` (graph watermark, all-lowercase) | → `'zunzunng'` (preserve lowercase convention) |
| `zunzun/apps.py:23` | `"zunzunsite3: missing external binaries on PATH: %s. "` (startup log prefix) | → `"zunzunng: ..."` |
| `zunzun/platform_compat.py:1` | `"""Platform-specific shim layer for zunzunsite3.` (module docstring) | → `"""Platform-specific shim layer for zunzunng.` |

### Smoke test (1 file, potentially)

`scripts/smoke_test.py` has assertion strings that check for substring markers in rendered HTML. Any assertion that hard-codes `ZunZunSite3` needs updating. Pre-implementation step: `grep -n 'ZunZun' scripts/smoke_test.py` and update every matching line that references content we're renaming. If all matches reference strings we've renamed above, smoke updates go in the same commit.

**Total:** 25 user-visible substitutions + 1 HTML rewrite + smoke-test assertion updates across 15 source files.

## Substitution rules

Applied per-hit with case awareness:

1. **Display text, page titles, headers, email subjects, PDF credit lines, user-facing error messages:** `ZunZunSite3` → `ZunZunNG` (mixed case — matches brand).
2. **Log prefixes, module docstrings, graph watermarks:** `zunzunsite3` → `zunzunng` (lowercase — matches package name / existing lowercase convention).
3. **Upstream repository URL:** `https://bitbucket.org/zunzuncode/zunzunsite3` → `https://github.com/kiloscheffer/zunzunng`. This applies even while `github.com/kiloscheffer/zunzunng` is private; PDFs generated before the public flip will have a temporarily-404ing link, which is acceptable because PDFs are durable artifacts — we prefer a link that eventually works to one that permanently points at someone else's dormant repo.
4. **Google group URL:** `http://groups.google.com/group/zunzun_dot_com/` → `https://groups.google.com/g/findcurves` (lowercase slug — Google's URL format) + upgrade `http` → `https`.
5. **Google group display label:** `ZunZunSite3 Google Group` → `FindCurves Google Group` (CamelCase in display, matching the group's self-branding).

## about.html rewrite

Current content (`templates/zunzun/divs/about.html`, 10 lines):

```html
<div ID="aboutDiv" align='center' name="hideable_div" style="display:none;">
<B><FONT SIZE="+1">About ZunZunSite3</FONT></B><BR><BR>
This site is dedicated to Jesus of Nazareth, and was written by James R. Phillips.<BR>
<BR>
The site is a natural outgrowth of my previous Research and Development days in Washington, D.C.,<BR>
my previous software engineering work in Tokyo, Japan and now in Birmingham, AL, USA.<BR>
<BR><BR>
The name of the project, ZunZunSite3, is taken from my wife's Burmese nickname.<BR>
</div>
```

Replace with a two-section layout. The NG section is the lead (reflects current maintenance); Phillips's section follows as "historical origin" with his prose preserved **verbatim**:

```html
<div ID="aboutDiv" align='center' name="hideable_div" style="display:none;">
<B><FONT SIZE="+1">About ZunZunNG</FONT></B><BR><BR>
ZunZunNG (Next Generation) is a permanent fork of ZunZunSite3, maintained by Kilo Scheffer since 2026.<BR>
<BR>
The fork modernizes the codebase for cross-platform deployment (Linux, macOS, Windows) on Python 3.14<BR>
and Django 6.0, replaces the original os.fork() architecture with multiprocessing.Process(spawn), and<BR>
drops the scipy.odr dependency via the companion <a href="https://github.com/kiloscheffer/pyeq3ng">pyeq3ng</a> fork.<BR>
<BR>
Source: <a href="https://github.com/kiloscheffer/zunzunng">github.com/kiloscheffer/zunzunng</a>.<BR>
Discussion: <a href="https://groups.google.com/g/findcurves">FindCurves Google Group</a>.<BR>
<BR><BR>

<B><FONT SIZE="+1">About the original ZunZunSite3 (James R. Phillips, 2016)</FONT></B><BR><BR>
This site is dedicated to Jesus of Nazareth, and was written by James R. Phillips.<BR>
<BR>
The site is a natural outgrowth of my previous Research and Development days in Washington, D.C.,<BR>
my previous software engineering work in Tokyo, Japan and now in Birmingham, AL, USA.<BR>
<BR><BR>
The name of the project, ZunZunSite3, is taken from my wife's Burmese nickname.<BR>
</div>
```

Design notes:

- The four content lines of Phillips's prose are preserved **byte-for-byte** (dedication, personal history, nickname origin). Changing even the capitalization would be disrespectful and would muddy the BSD-2-clause attribution trail.
- Phillips's section gets a new `<B>` heading with explicit authorship + year (`James R. Phillips, 2016`). This disambiguates the "my wife" / "my previous Research and Development days" first-person voice — without the header, a reader might wrongly infer those are Kilo Scheffer's words.
- The NG section uses the same `<B><FONT SIZE="+1">...</FONT></B>` heading style as the original to match the template's visual convention.
- The outer `<div>` attributes (`ID`, `align`, `name`, `style="display:none;"`) are unchanged so the existing show/hide JavaScript on the home page continues to work without changes.
- No new `<div>` wrappers inside — the two sections are visually separated by the existing `<BR><BR>` + heading-style-reset pattern the rest of the site uses.

## Verification

1. **Pre-change baseline.** `UV_LINK_MODE=copy uv run pytest tests/ -v` → 78/78. `UV_LINK_MODE=copy uv run python scripts/smoke_test.py` → 12/12. Confirmed green before any substitution.
2. **Static sweep.** After substitutions, re-run `grep -ri 'zunzunsite3\|ZunZunSite3' templates/ zunzun/ scripts/` — expect zero matches in user-visible surface (matches are allowed in `docs/`, `TODO.md`'s RESOLVED sections, `LICENSE.txt`, `DEDICATION.txt`, `CHANGELOG`'s historical reference line, and `.claude/agents/`).
3. **Post-change unit tests.** `UV_LINK_MODE=copy uv run pytest tests/ -v` → 78/78. String substitutions don't change code paths, so pass is expected.
4. **Post-change smoke.** `UV_LINK_MODE=copy uv run python scripts/smoke_test.py` → 12/12 with updated assertion strings. Budget: 1–5 min on Linux/macOS, 3–5 min on Windows.
5. **Manual PDF spot-check (optional).** Run the home-page, request a fit, open the generated PDF from `temp/`, visually confirm: (a) `ZunZunNG` credit string present, (b) watermark URL is github, (c) graph watermark reads `zunzunng`. Not required for correctness — the smoke test exercises PDF generation end-to-end — but a 30-second sanity check.

## Commit structure

**Single commit** named `"Complete ZunZunNG rebrand in user-facing strings"` on a `zunzunng-branding` feature branch off `master`, merged back via `--no-ff` to preserve the branch topology. Single-commit rationale: the scope is small (~25 mechanical substitutions + one HTML rewrite + smoke update), and splitting would introduce intermediate states where the codebase is half-rebranded (e.g., page title says `ZunZunNG` but home-page header still says `ZunZunSite3`). The about.html rewrite is ~15 lines of HTML review inside the same diff — adding no meaningful review burden beyond the mechanical substitutions.

Commit body should summarize:
- The five substitution rules in §"Substitution rules"
- The two-section about.html design
- Verification output (78/78 + 12/12)
- Reference this spec file

## Risks and open issues

- **PDF watermark URL will 404 until public flip.** Accepted per Q2. Mitigation: once `github.com/kiloscheffer/zunzunng` flips public, the URL starts working without any code change.
- **If `scripts/smoke_test.py` has assertions on `ZunZunSite3` that match templates we're renaming, the commit must update them atomically to keep smoke green.** This is why `scripts/smoke_test.py` is listed in §"Scope" — pre-implementation step is to grep and enumerate.
- **The `about.html` show/hide JavaScript must continue to work.** Risk mitigated by preserving the outer `<div>` attributes unchanged. Tested implicitly by smoke's home-page scenario.
- **Dropbox sync during the commit.** The working tree is in a Dropbox folder. Mid-edit Dropbox can create `.conflict` files if multiple machines touch the same path. Mitigation: confirm no other Dropbox-synced machine is running the `uv` toolchain or editing these files during the rebrand.
- **Permission: the repo is currently private.** The smoke test and pytest run entirely locally, so private state doesn't block verification. Pushing happens after merge to master per normal workflow.

## Not in this spec

Flipping `github.com/kiloscheffer/zunzunng` from private to public is a separate decision outside this spec. When that flip happens, a follow-up may address: whether to enable GitHub Discussions (which could supplement or replace the FindCurves group as a forum), the fate of the `upstream` remote pointer at the dormant Bitbucket repo, and any README badges.
