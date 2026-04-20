# ZunZunNG Branding — User-Visible String Rebrand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every user-visible `ZunZunSite3` / `zunzunsite3` / bitbucket-URL / legacy Google-group reference with the ZunZunNG equivalent across templates, views, LRP subclasses, watermarks, logs, and smoke test assertions, in a single implementation commit on the `zunzunng-branding` feature branch.

**Architecture:** Pure text substitution driven by the five rules in `docs/superpowers/specs/2026-04-20-zunzunng-branding-design.md`. No behavior changes; the gating tests are (a) zero `ZunZunSite3` matches in the user-visible surface after edits, (b) pytest 78/78 pass, (c) smoke 12/12 pass. The `about.html` two-section rewrite preserves James R. Phillips's prose verbatim while introducing a ZunZunNG section above it.

**Tech Stack:** Python 3.14, Django 6.0 templates, matplotlib, reportlab, pytest, requests-based smoke script.

---

## Pre-flight notes

- **Branch:** `zunzunng-branding`, already created. Current HEAD is commit `3eb306c` (design spec). All implementation happens on this branch.
- **Design spec:** `docs/superpowers/specs/2026-04-20-zunzunng-branding-design.md` — read this first. The plan implements that spec with zero deviation.
- **Commit discipline:** per spec, **one** implementation commit. The plan document commit (Task 1) and the design spec commit (pre-existing) are separate. Then `--no-ff` merge to master.
- **Line numbers:** all line references in this plan are against commit `a43034c` (top-level rebrand) which is the branch point. Steps include a `Read` verification to catch drift before editing.
- **Working directory:** `C:\Dropbox\git\zunzunsite3\` under Dropbox sync. Use `UV_LINK_MODE=copy` prefix on all uv commands per user memory.
- **Smoke runtime budget:** 3–5 min on Windows. Expect two full smoke runs (baseline + post-change) — ~10 minutes of the total implementation time.

---

## Task 1: Commit the plan document

**Files:**
- Create: `docs/superpowers/plans/2026-04-20-zunzunng-branding.md` (this file)

- [ ] **Step 1: Verify branch is `zunzunng-branding` and tree clean**

Run: `git status -sb && git log --oneline -3`
Expected: current branch `zunzunng-branding`, working tree clean except for this plan file being untracked.

- [ ] **Step 2: Commit the plan**

```bash
git add docs/superpowers/plans/2026-04-20-zunzunng-branding.md
git commit -m "$(cat <<'EOF'
Plan: ZunZunNG branding — user-visible string rebrand

Implementation plan for docs/superpowers/specs/2026-04-20-zunzunng-
branding-design.md. Seven tasks covering baseline verification, ~25
user-visible substitutions across ~15 files, the about.html two-
section rewrite, smoke-test assertion updates, post-change
verification, single implementation commit, and merge to master.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: commit created with hash displayed; `git log --oneline -2` shows plan commit then design commit.

---

## Task 2: Baseline verification

Confirm the codebase is green before any substitutions. If anything fails here, stop — do not proceed with rebrand edits until baseline is clean.

**Files:** none modified.

- [ ] **Step 1: Run pytest**

Run: `UV_LINK_MODE=copy uv run pytest tests/ -v`
Expected: `78 passed` in ~18s. If fewer pass or any fail, stop and investigate.

- [ ] **Step 2: Run smoke test**

Run: `UV_LINK_MODE=copy uv run python scripts/smoke_test.py`
Expected: all 12 scenarios pass, summary line `12/12 scenarios passed`. Takes 3–5 min on Windows. If anything fails, stop and investigate before proceeding.

---

## Task 3: Apply all user-visible substitutions

Single bulk edit pass. Every edit is an exact `Edit` tool call on a specific file with exact `old_string` and `new_string`. No commits inside this task — all edits are gathered into the single implementation commit (Task 6).

### 3a: Templates (9 files, excluding about.html)

**Files modified:**
- `templates/zunzun/home_page.html` (3 hits across 3 locations)
- `templates/zunzun/divs/feedback_entry.html` (1 hit)
- `templates/zunzun/feedback_reply.html` (1 hit)
- `templates/zunzun/function_finder_interface.html` (2 hits)
- `templates/zunzun/function_finder_results.html` (1 hit)
- `templates/zunzun/generic_error.html` (1 hit)
- `templates/zunzun/generic_page_template.html` (1 hit)
- `templates/zunzun/invalid_form_data.html` (1 hit)
- `templates/zunzun/list_all_equations.html` (1 hit)

- [ ] **Step 1: Edit `templates/zunzun/home_page.html` — welcome header**

`old_string`:
```
<B><FONT SIZE="+1">Welcome to ZunZunSite3</FONT></B><BR><BR>
```
`new_string`:
```
<B><FONT SIZE="+1">Welcome to ZunZunNG</FONT></B><BR><BR>
```

- [ ] **Step 2: Edit `templates/zunzun/home_page.html` — Bitbucket "Code Repository" link**

`old_string`:
```
the site for you! Source code is available at the <a href="https://bitbucket.org/zunzuncode/zunzunsite3">Bitbucket Code Repository</a>.<br>
```
`new_string`:
```
the site for you! Source code is available at the <a href="https://github.com/kiloscheffer/zunzunng">GitHub Code Repository</a>.<br>
```

- [ ] **Step 3: Edit `templates/zunzun/home_page.html` — Google-group icon alt text + URL (line 149)**

`old_string`:
```
    <TD ALIGN="CENTER"><a href="http://groups.google.com/group/zunzun_dot_com/"><img src="/temp/static_images/groups_logo.gif" BORDER="0" alt="ZunZunSite3 Google Group"></A></TD>
```
`new_string`:
```
    <TD ALIGN="CENTER"><a href="https://groups.google.com/g/findcurves"><img src="/temp/static_images/groups_logo.gif" BORDER="0" alt="FindCurves Google Group"></A></TD>
```

- [ ] **Step 4: Edit `templates/zunzun/home_page.html` — Google-group discussion group link text (line 156)**

`old_string`:
```
    <TD ALIGN="CENTER">ZunZunSite3's<A HREF="http://groups.google.com/group/zunzun_dot_com/"> Google<br>discussion group</A></TD>
```
`new_string`:
```
    <TD ALIGN="CENTER">FindCurves<A HREF="https://groups.google.com/g/findcurves"> Google<br>discussion group</A></TD>
```

- [ ] **Step 5: Edit `templates/zunzun/divs/feedback_entry.html` — Google-group link**

`old_string`:
```
or try the ZunZunSite3 <a href='http://groups.google.com/group/zunzun_dot_com/'>Google discussion group</a>.
```
`new_string`:
```
or try the FindCurves <a href='https://groups.google.com/g/findcurves'>Google discussion group</a>.
```

- [ ] **Step 6: Edit `templates/zunzun/feedback_reply.html` — return-to text**

`old_string`:
```
Please close this window to return to ZunZunSite3.</font>
```
`new_string`:
```
Please close this window to return to ZunZunNG.</font>
```

- [ ] **Step 7: Edit `templates/zunzun/function_finder_interface.html` — title (line 4)**

`old_string`:
```
    ZunZunSite3 - {{ dimensionality }}D Function Finder
```
`new_string`:
```
    ZunZunNG - {{ dimensionality }}D Function Finder
```

- [ ] **Step 8: Edit `templates/zunzun/function_finder_interface.html` — Bitbucket Home link (line 50)**

`old_string`:
```
    <TD><BASEFONT SIZE="3"><A HREF="https://bitbucket.org/zunzuncode/zunzunsite3" TARGET="_parent">Home</A></TD>
```
`new_string`:
```
    <TD><BASEFONT SIZE="3"><A HREF="https://github.com/kiloscheffer/zunzunng" TARGET="_parent">Home</A></TD>
```

- [ ] **Step 9: Edit `templates/zunzun/function_finder_results.html` — title (line 4)**

`old_string`:
```
    ZunZunSite3 - {{ dimensionality }}D Function Finder Results
```
`new_string`:
```
    ZunZunNG - {{ dimensionality }}D Function Finder Results
```

- [ ] **Step 10: Edit `templates/zunzun/generic_error.html` — title (line 4)**

`old_string`:
```
    ZunZunSite3 Curve Fitting and Surface Fitting
```
`new_string`:
```
    ZunZunNG Curve Fitting and Surface Fitting
```

- [ ] **Step 11: Edit `templates/zunzun/generic_page_template.html` — Django (this site) link**

`old_string`:
```
<a href=https://bitbucket.org/zunzuncode/zunzunsite3>Django (this site)</a>
```
`new_string`:
```
<a href=https://github.com/kiloscheffer/zunzunng>Django (this site)</a>
```

- [ ] **Step 12: Edit `templates/zunzun/invalid_form_data.html` — title (line 4)**

`old_string`:
```
    ZunZunSite3 Curve Fitting and Surface Fitting
```
`new_string`:
```
    ZunZunNG Curve Fitting and Surface Fitting
```

- [ ] **Step 13: Edit `templates/zunzun/list_all_equations.html` — title (line 4)**

`old_string`:
```
    ZunZunSite3 Curve Fitting and Surface Fitting
```
`new_string`:
```
    ZunZunNG Curve Fitting and Surface Fitting
```

### 3b: `templates/zunzun/divs/about.html` — two-section rewrite

**File:** `templates/zunzun/divs/about.html` (entire file replacement, 10 lines → ~20 lines).

- [ ] **Step 14: Replace entire file with two-section design**

Use `Write` tool (full file replacement) with this exact content:

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

Note: Phillips's four prose lines (starting with "This site is dedicated..." and ending with "...Burmese nickname.") are **byte-for-byte identical** to the pre-change version. The only changes to his section are the new `<B>` heading above it. Do not touch the prose content.

### 3c: `zunzun/views.py` (5 hits)

**File:** `zunzun/views.py` (5 string substitutions)

- [ ] **Step 15: Edit `zunzun/views.py:261` — cookie error message**

`old_string`:
```
        return HttpResponse("I could not read your session data, my apologies. This is usually caused by a stale browser cookie. Please delete the zunzunsite3 browser cookie and try again.")
```
`new_string`:
```
        return HttpResponse("I could not read your session data, my apologies. This is usually caused by a stale browser cookie. Please delete the ZunZunNG browser cookie and try again.")
```

- [ ] **Step 16: Edit `zunzun/views.py:513` — email subject**

`old_string`:
```
            EmailMessage('ZunZunSite3 Feedback Form', msg, to = [settings.FEEDBACK_EMAIL_ADDRESS]).send()
```
`new_string`:
```
            EmailMessage('ZunZunNG Feedback Form', msg, to = [settings.FEEDBACK_EMAIL_ADDRESS]).send()
```

- [ ] **Step 17: Edit `zunzun/views.py:549` — home page header**

`old_string`:
```
    items_to_render['header_text'] = 'ZunZunSite3 Online Curve Fitting<br>and Surface Fitting Web Site'
```
`new_string`:
```
    items_to_render['header_text'] = 'ZunZunNG Online Curve Fitting<br>and Surface Fitting Web Site'
```

- [ ] **Step 18: Edit `zunzun/views.py:576` — list-all header (all)**

`old_string`:
```
        items_to_render['header_text'] = 'ZunZunSite3 List Of All ' + inDimensionality + 'D Equations'
```
`new_string`:
```
        items_to_render['header_text'] = 'ZunZunNG List Of All ' + inDimensionality + 'D Equations'
```

- [ ] **Step 19: Edit `zunzun/views.py:578` — list-all header (standard)**

`old_string`:
```
        items_to_render['header_text'] = 'ZunZunSite3 List Of All Standard ' + inDimensionality + 'D Equations'
```
`new_string`:
```
        items_to_render['header_text'] = 'ZunZunNG List Of All Standard ' + inDimensionality + 'D Equations'
```

### 3d: LRP subclasses (4 files)

- [ ] **Step 20: Edit `zunzun/LongRunningProcess/FittingBaseClass.py:189`**

`old_string`:
```
        self.dictionaryToReturn['title_string'] = 'ZunZunSite3 - ' + self.equation.GetDisplayName() + ' Fitting Interface'
```
`new_string`:
```
        self.dictionaryToReturn['title_string'] = 'ZunZunNG - ' + self.equation.GetDisplayName() + ' Fitting Interface'
```

- [ ] **Step 21: Edit `zunzun/LongRunningProcess/FunctionFinder.py:565-566` (both header and title)**

`old_string`:
```
        dictionaryToReturn['header_text'] = 'ZunZunSite3 ' + str(self.dimensionality) + 'D Function Finder Interface'
        dictionaryToReturn['title_string'] = 'ZunZunSite3 ' + str(self.dimensionality) + 'D Function Finder Interface'
```
`new_string`:
```
        dictionaryToReturn['header_text'] = 'ZunZunNG ' + str(self.dimensionality) + 'D Function Finder Interface'
        dictionaryToReturn['title_string'] = 'ZunZunNG ' + str(self.dimensionality) + 'D Function Finder Interface'
```

- [ ] **Step 22: Edit `zunzun/LongRunningProcess/FunctionFinderResults.py:113-114` (both header and title)**

`old_string`:
```
        itemsToRender['header_text'] = 'ZunZunSite3<br>' + str(self.dataObject.dimensionality) + 'D ' + self.webFormName
        itemsToRender['title_string'] = 'ZunZunSite3 ' + str(self.dataObject.dimensionality) + 'D ' + self.webFormName
```
`new_string`:
```
        itemsToRender['header_text'] = 'ZunZunNG<br>' + str(self.dataObject.dimensionality) + 'D ' + self.webFormName
        itemsToRender['title_string'] = 'ZunZunNG ' + str(self.dataObject.dimensionality) + 'D ' + self.webFormName
```

- [ ] **Step 23: Edit `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py:128` — PDF watermark URL**

`old_string`:
```
        self.drawCentredString(25*mm, 20*mm, 'https://bitbucket.org/zunzuncode/zunzunsite3')
```
`new_string`:
```
        self.drawCentredString(25*mm, 20*mm, 'https://github.com/kiloscheffer/zunzunng')
```

- [ ] **Step 24: Edit `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py:269` — PDF credit string**

`old_string`:
```
            tableRow = [largeLogoImage,
                        'ZunZunSite3',
                        largeLogoImage]
```
`new_string`:
```
            tableRow = [largeLogoImage,
                        'ZunZunNG',
                        largeLogoImage]
```

- [ ] **Step 25: Edit `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py:825-826` — LRP header/title (first pair)**

`old_string`:
```
        itemsToRender['header_text'] = 'ZunZunSite3<br>' + self.webFormName
        itemsToRender['title_string'] = 'ZunZunSite3 ' + self.webFormName.replace('<br>', ' ')
```
`new_string`:
```
        itemsToRender['header_text'] = 'ZunZunNG<br>' + self.webFormName
        itemsToRender['title_string'] = 'ZunZunNG ' + self.webFormName.replace('<br>', ' ')
```

- [ ] **Step 26: Edit `zunzun/LongRunningProcess/StatusMonitoredLongRunningProcessPage.py:884-885` — LRP header/title (second pair)**

`old_string`:
```
        dictionaryToReturn['header_text'] = 'ZunZunSite3 ' + str(self.dimensionality) + 'D Interface<br>' + self.webFormName
        dictionaryToReturn['title_string'] = 'ZunZunSite3 ' + str(self.dimensionality) + 'D Interface ' + self.webFormName
```
`new_string`:
```
        dictionaryToReturn['header_text'] = 'ZunZunNG ' + str(self.dimensionality) + 'D Interface<br>' + self.webFormName
        dictionaryToReturn['title_string'] = 'ZunZunNG ' + str(self.dimensionality) + 'D Interface ' + self.webFormName
```

### 3e: Graph watermark + log prefix + module docstring

- [ ] **Step 27: Edit `zunzun/LongRunningProcess/MatplotlibGraphs_2D.py:94` — graph watermark**

`old_string`:
```
        ax.text(relativeWidthPos, relativeHeightPos, 'zunzunsite3',
```
`new_string`:
```
        ax.text(relativeWidthPos, relativeHeightPos, 'zunzunng',
```

- [ ] **Step 28: Edit `zunzun/apps.py:23` — startup log prefix**

`old_string`:
```
                "zunzunsite3: missing external binaries on PATH: %s. "
```
`new_string`:
```
                "zunzunng: missing external binaries on PATH: %s. "
```

- [ ] **Step 29: Edit `zunzun/platform_compat.py:1` — module docstring**

`old_string`:
```
"""Platform-specific shim layer for zunzunsite3.
```
`new_string`:
```
"""Platform-specific shim layer for zunzunng.
```

### 3f: Smoke test assertion updates

- [ ] **Step 30: Edit `scripts/smoke_test.py:276` — comment (cosmetic)**

`old_string`:
```
    # The header is "ZunZunSite3 List Of All Standard 2D Equations"
```
`new_string`:
```
    # The header is "ZunZunNG List Of All Standard 2D Equations"
```

- [ ] **Step 31: Edit `scripts/smoke_test.py:297,299` — feedback GET marker**

`old_string`:
```
# /Feedback/ GET redirects to '/'; we only assert the redirect lands
# somewhere that renders the home page (non-empty, contains ZunZunSite3).
_FEEDBACK_GET_MARKERS = [
    "ZunZunSite3",
]
```
`new_string`:
```
# /Feedback/ GET redirects to '/'; we only assert the redirect lands
# somewhere that renders the home page (non-empty, contains ZunZunNG).
_FEEDBACK_GET_MARKERS = [
    "ZunZunNG",
]
```

---

## Task 4: Static grep verification

Verify the substitution sweep is complete. Zero matches expected in the user-visible surface after Task 3.

**Files:** none modified.

- [ ] **Step 1: Grep for any remaining matches in `templates/` and `zunzun/`**

Run: `grep -rin "zunzunsite3" templates/ zunzun/`
Expected: no matches. If any appear, investigate — there may be a case-variant or line-drifted hit missed by the enumerated steps.

- [ ] **Step 2: Grep for bitbucket URL references in scope**

Run: `grep -rin "bitbucket.org/zunzuncode" templates/ zunzun/`
Expected: no matches.

- [ ] **Step 3: Grep for legacy Google-group URL in scope**

Run: `grep -rin "zunzun_dot_com" templates/ zunzun/ scripts/`
Expected: no matches.

- [ ] **Step 4: Grep for remaining matches in `scripts/smoke_test.py`**

Run: `grep -n "ZunZun" scripts/smoke_test.py`
Expected: only `ZunZunNG` matches. No `ZunZunSite3`.

---

## Task 5: Post-change verification

Confirm tests still pass end-to-end.

**Files:** none modified.

- [ ] **Step 1: Run pytest**

Run: `UV_LINK_MODE=copy uv run pytest tests/ -v`
Expected: `78 passed` in ~18s. No regressions. If any fail, inspect the failure — string substitutions don't change code paths, so a failure means a syntax error (e.g., a Python string literal with embedded quote that got miscoded) or a test that was implicitly checking a rendered string.

- [ ] **Step 2: Run smoke test**

Run: `UV_LINK_MODE=copy uv run python scripts/smoke_test.py`
Expected: all 12 scenarios pass, `12/12 scenarios passed`. Budget 3–5 min on Windows.

- [ ] **Step 3 (optional): Manual spot-check**

Open `http://127.0.0.1:8000/` in a browser (start with `UV_LINK_MODE=copy uv run python manage.py runserver`), verify:
- Home page header reads `Welcome to ZunZunNG`.
- Click "About" — both sections (NG + Phillips) display correctly.
- Trigger a simple 2D polynomial-quadratic fit, open the generated PDF from `temp/`, verify: `ZunZunNG` credit string centered, watermark URL `https://github.com/kiloscheffer/zunzunng`.
- Verify a generated 2D graph (e.g., any `.png` in `temp/` from the fit) has `zunzunng` vertical watermark.

This step is optional because the smoke test exercises all these paths programmatically, but it's the fastest way to catch visual glitches (e.g., HTML entity issues, unwanted whitespace).

---

## Task 6: Single implementation commit

**Files:** commits the result of Task 3.

- [ ] **Step 1: Stage the expected set of files and review the diff**

Run:
```bash
git add templates/zunzun/ zunzun/views.py zunzun/apps.py zunzun/platform_compat.py zunzun/LongRunningProcess/ scripts/smoke_test.py
git status
git diff --cached --stat
```
Expected: ~15 files changed, a modest number of insertions/deletions skewed toward additions (from the about.html rewrite). Roughly 30-50 lines changed.

- [ ] **Step 2: Commit**

```bash
git commit -m "$(cat <<'EOF'
Complete ZunZunNG rebrand in user-facing strings

Apply the deferred follow-up to commit a43034c (top-level rebrand).
~25 user-visible substitutions across templates/, zunzun/views.py,
zunzun/LongRunningProcess/, zunzun/apps.py, zunzun/platform_compat.py,
plus a two-section rewrite of templates/zunzun/divs/about.html and
smoke-test assertion updates.

Five substitution rules applied:
1. Mixed-case display: ZunZunSite3 → ZunZunNG (page titles, headers,
   email subject, cookie-error message, PDF credit string).
2. Lowercase logs/watermarks: zunzunsite3 → zunzunng (graph watermark,
   apps.py startup log, platform_compat.py module docstring).
3. Upstream URL: bitbucket.org/zunzuncode/zunzunsite3 →
   github.com/kiloscheffer/zunzunng (PDF watermark, home-page link,
   generic-page-template link, function-finder-interface Home link).
4. Google-group URL: http://groups.google.com/group/zunzun_dot_com/ →
   https://groups.google.com/g/findcurves (home_page.html × 2,
   feedback_entry.html × 1). HTTP → HTTPS upgrade included.
5. Google-group display label: ZunZunSite3 Google Group → FindCurves
   Google Group.

about.html rewrite: two adjacent sections inside the same aboutDiv.
NG section (leading, authored by Kilo Scheffer) covers the fork's
identity, source URL, and FindCurves discussion group. Phillips's
original prose is preserved byte-for-byte in a "About the original
ZunZunSite3 (James R. Phillips, 2016)" section below, with a new
explicit-authorship heading to disambiguate his first-person voice
("my wife", "my previous Research and Development days") from the
current maintainer's. The outer div attributes (ID, align, name,
style) are unchanged so the home page's existing show/hide
JavaScript continues to work.

Verification: pytest 78/78 + smoke 12/12 both pass pre and post.
Static grep for 'zunzunsite3\|ZunZunSite3' in templates/ and zunzun/
returns zero matches. PDF watermark URL will 404 until the
github.com/kiloscheffer/zunzunng repo flips public; accepted per
design Q2.

See docs/superpowers/specs/2026-04-20-zunzunng-branding-design.md
and docs/superpowers/plans/2026-04-20-zunzunng-branding.md for
design and execution records.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: single commit on `zunzunng-branding` branch. `git log --oneline zunzunng-branding ^master` shows three commits: the design (`3eb306c`), the plan (from Task 1), and this implementation commit.

---

## Task 7: Merge to master and push

**Files:** no source changes; this is repo-level work.

- [ ] **Step 1: Checkout master**

Run: `git checkout master`
Expected: `Switched to branch 'master'`. Verify with `git status -sb` — should show `## master...origin/master` clean.

- [ ] **Step 2: Merge feature branch with --no-ff**

Run:
```bash
git merge --no-ff zunzunng-branding -m "$(cat <<'EOF'
Merge zunzunng-branding: complete ZunZunNG rebrand in user-facing strings

Closes the "Complete ZunZunNG rebrand in user-facing strings" TODO
entry. Contains the design spec, implementation plan, and the single
implementation commit.
EOF
)"
```
Expected: merge commit created on master. `git log --oneline -5` shows the merge commit at HEAD, followed by the three branch commits.

- [ ] **Step 3: Update TODO.md — mark the rebrand-followup entry RESOLVED**

Edit `TODO.md`: find the `## Complete ZunZunNG rebrand in user-facing strings` heading and replace it with a resolution block matching the pattern used by previously-closed entries (strikethrough heading + `RESOLVED YYYY-MM-DD` + `> **Resolution.**` block summarizing what landed).

Exact edit:

`old_string`:
```
## Complete ZunZunNG rebrand in user-facing strings
```
`new_string`:
```
## ~~Complete ZunZunNG rebrand in user-facing strings~~ RESOLVED 2026-04-20

> **Resolution.** Landed on a dedicated `zunzunng-branding` feature
> branch and merged to master via `--no-ff`. Applied the five
> substitution rules from the design spec across ~15 files: display-
> text `ZunZunSite3` → `ZunZunNG`, lowercase `zunzunsite3` → `zunzunng`,
> bitbucket upstream URL → `github.com/kiloscheffer/zunzunng`, legacy
> Google-group URL → `https://groups.google.com/g/findcurves`,
> display label → `FindCurves Google Group`. `about.html` rewritten
> as two sections preserving James R. Phillips's original prose
> byte-for-byte. pytest 78/78 + smoke 12/12 stayed green. See
> `docs/superpowers/specs/2026-04-20-zunzunng-branding-design.md`
> and `docs/superpowers/plans/2026-04-20-zunzunng-branding.md`.
>
> Historical notes below, preserved for reference.
```

Then commit the TODO update:

```bash
git add TODO.md
git commit -m "$(cat <<'EOF'
Close ZunZunNG rebrand TODO as RESOLVED

Mark the 'Complete ZunZunNG rebrand in user-facing strings' entry
resolved following the zunzunng-branding merge.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Push master + feature branch + any new state**

Run:
```bash
git push origin master
git push origin zunzunng-branding
```
Expected: both refs pushed to `github.com/kiloscheffer/zunzunng`. Master shows merge commit + resolution commit at HEAD; feature branch preserved for future reference.

- [ ] **Step 5: Verify remote state matches local**

Run: `git ls-remote origin | head -10`
Expected: `HEAD` and `refs/heads/master` point at the same commit (the TODO-close commit), `refs/heads/zunzunng-branding` points at the implementation commit, `refs/tags/v1.0.0-ng` still points at the top-level rebrand commit (`a43034c`'s tree — this rebrand doesn't bump the tag).

---

## Rollback plan

If Task 5 (post-change verification) fails and the failure isn't a fixable typo:

1. `git restore --source=HEAD templates/ zunzun/ scripts/smoke_test.py` — revert working tree changes.
2. Re-run pytest + smoke to confirm baseline is clean again.
3. Investigate the specific failure, update the relevant task steps in this plan, re-attempt.

If Task 7 merge is complete but post-merge smoke fails on master:

1. `git revert -m 1 <merge-commit-sha>` — creates a revert commit undoing the merge.
2. Push the revert.
3. Diagnose and re-do on a fresh branch.

Do NOT use `git reset --hard` to undo a merge that has been pushed — that's a published-history rewrite.
