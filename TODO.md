# TODO — known deferred issues

Tracked items that are real defects or loose ends, but are scoped out of the
current branch. Each entry documents the symptom, the hypothesis, what we
*didn't* do, and where to pick up from.

## 3D fit spawn-Pool deadlock on Windows smoke

**Symptom.** When `scripts/smoke_test.py` runs a 3D polynomial-quadratic fit
against a 12-point (X, Y, Z) grid (`/FitEquation__F__/3/Polynomial/Full Quadratic/`),
the smoke harness never sees the final result body. The main waitress-server
python.exe silently stops writing output ~15 matplotlib reports into the fit's
report generation and stays idle for 80+ minutes with 3 zombie spawn-Pool
workers at ~5 MB resident each. Manual click-through on the live server works
fine — the deadlock is only reproducible under smoke.

**When we hit it.** 2026-04-18, Phase 1 of the Django 2.2 → 5.2 LTS migration
(plan: `docs/superpowers/plans/2026-04-18-django-upgrade.md`, Task 4).

**Hypothesis.** A spawn-Pool worker dies silently during matplotlib report
rendering (OOM? import race? ImageMagick `magick mogrify` shellout hang?).
The parent's `pool.map_async(...).get()` blocks forever because spawn on
Windows has no equivalent of SIGCHLD — a dead child is indistinguishable from
a slow child. 2D fits generate ~4 reports per run; 3D generates ~15. Exposure
probability scales with report count, which is why 2D smoke has been stable
across dozens of runs and 3D tripped immediately.

**What we did instead.** Dropped the `polynomial_quadratic_3D` scenario from
the smoke test. The final smoke suite has 8 scenarios (was planned to be 9).
This preserves the migration's test-expansion intent for every other path but
leaves 3D coverage as a known hole.

**Where to pick up.**
- Reproduce: uncomment the `_DATA_3D_POLY` / `_POLY_QUAD_3D_FIELDS` / scenario
  block from the plan's Task 4 and run `uv run python scripts/smoke_test.py`.
  Budget ≥30 min; deadlock currently happens around the 15th `.png` written
  to `temp/`.
- Diagnose options (pick one):
  1. Instrument `CreateOutputReportsInParallelUsingProcessPool` in
     `StatusMonitoredLongRunningProcessPage.py` to log per-worker lifecycle
     events (enter / exit / exception); rerun the 3D smoke and see which
     worker doesn't emit an exit event.
  2. Replace `multiprocessing.Pool` with `concurrent.futures.ProcessPoolExecutor`
     which surfaces child exceptions on `.result()` rather than swallowing them.
  3. Add a per-worker wall-clock timeout wrapper; if a worker exceeds N seconds,
     force-kill and fail the fit rather than hanging.
- Fix (TBD — depends on diagnosis). Likely a small pyeq3/matplotlib interaction
  patch or a pool-wrapper change in the LRP base class. Unrelated to anything
  else in the Django migration.

**Not in scope of the Django 5.2 branch.** Fixing this deserves its own
branch and its own spec/plan cycle, since the root cause is in the
spawn-Pool pattern (shared with the cross-platform migration), not in
Django version compatibility.
