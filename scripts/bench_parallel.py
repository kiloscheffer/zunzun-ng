"""Benchmark threading vs spawn-fresh vs persistent-pool for pyeq3 fits.

Usage:
    uv run python scripts/bench_parallel.py

Compares four execution modes for N=16 identical pyeq3 fits:
    serial           — single-threaded baseline
    threaded         — concurrent.futures.ThreadPoolExecutor(max_workers=N)
    spawn-fresh      — multiprocessing.Process per fit, joined per fit (current
                       FunctionFinder pattern)
    pool-persistent  — concurrent.futures.ProcessPoolExecutor(max_workers=N)
                       with spawn context, workers reused across all N fits
                       (the proposed pattern)

Reports wall-clock time per mode. Peak RSS sampled per parent during the run.

Each "fit" is a SolveUsingDE + SolveUsingSelectedAlgorithm pass on a 2D
polynomial (5 coefficients) against 40 synthetic data points — small enough
to keep total runtime under a few minutes, large enough that fit cost
dominates over harness overhead.
"""

# Baseline 2026-05-27 on 22-core Windows box, Python 3.14.4, ~10 GB RAM available:
#   serial:                 8.04s  (1.00x)  145 MB peak RSS
#   threaded (8 threads):   8.56s  (0.94x)  149 MB peak RSS  ← slower than serial; GIL held
#   spawn-fresh (8 procs):  6.19s  (1.30x)  1.28 GB peak RSS
#   pool-persistent (8):    3.86s  (2.09x)  1.28 GB peak RSS  ← proposed pattern
# If a future run shows worse than 1.5x speedup for pool-persistent vs serial,
# something has regressed in the parallel path or pyeq3 hot-path.

from __future__ import annotations

import concurrent.futures
import multiprocessing
import os
import sys
import threading
import time
from multiprocessing.process import BaseProcess
from typing import Callable

import numpy
import psutil

N_FITS = 16
N_WORKERS = 8


def _make_synthetic_data(seed: int = 7) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Return (independent_data_2D, dependent_data) shaped to pyeq3's expected layout."""
    rng = numpy.random.default_rng(seed)
    x = numpy.linspace(0.5, 10.0, 80)
    y_true = 2.3 * numpy.exp(0.31 * x) + 1.1
    y = y_true + rng.normal(0.0, 0.5, size=x.shape)
    independent = numpy.array([x, numpy.ones_like(x)])
    return independent, y


def _fit_once(_unused: int) -> float:
    """Run one pyeq3 nonlinear fit; return the fittingTarget value.

    Forces the slow path (DE + Levenberg-Marquardt + simplex) by setting
    upperCoefficientBounds, which makes CanLinearSolverBeUsedForSSQABS()
    return False inside IModel.Solve. This is the path the FunctionFinder
    parallel workers actually traverse — linear-solvable equations are run
    serially in the parent (FunctionFinder.serialWorker).
    """
    import pyeq3

    independent, dependent = _make_synthetic_data()
    equation = pyeq3.Models_2D.Exponential.SimpleExponential("SSQABS", "Offset")
    equation.upperCoefficientBounds = [100.0, 5.0, 100.0]
    equation.dataCache.allDataCacheDictionary["IndependentData"] = independent
    equation.dataCache.allDataCacheDictionary["DependentData"] = dependent
    equation.dataCache.allDataCacheDictionary["Weights"] = []
    equation.dataCache.FindOrCreateAllDataCache(equation)
    equation.Solve()
    return float(equation.CalculateAllDataFittingTarget(equation.solvedCoefficients))


def _bench_serial(n: int) -> tuple[float, list[float]]:
    t0 = time.perf_counter()
    results = [_fit_once(i) for i in range(n)]
    return time.perf_counter() - t0, results


def _bench_threaded(n: int, max_workers: int) -> tuple[float, list[float]]:
    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(_fit_once, range(n)))
    return time.perf_counter() - t0, results


def _spawn_fresh_one(i: int, q: multiprocessing.Queue) -> None:
    q.put(_fit_once(i))


def _bench_spawn_fresh(n: int, max_concurrent: int) -> tuple[float, list[float]]:
    """Spawn one fresh Process per fit, with at most max_concurrent in flight.

    Mirrors the current FunctionFinder.PerformWorkInParallel pattern: tasks
    arrive as fresh processes that pay the full import cost on startup.
    """
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    t0 = time.perf_counter()

    in_flight: list[BaseProcess] = []
    submitted = 0
    results: list[float] = []

    while submitted < n or in_flight:
        while submitted < n and len(in_flight) < max_concurrent:
            p = ctx.Process(target=_spawn_fresh_one, args=(submitted, q))
            p.start()
            in_flight.append(p)
            submitted += 1
        time.sleep(0.05)
        still_alive: list[BaseProcess] = []
        for p in in_flight:
            if p.is_alive():
                still_alive.append(p)
            else:
                p.join()
        in_flight = still_alive
        while not q.empty():
            results.append(q.get())

    while not q.empty():
        results.append(q.get())
    return time.perf_counter() - t0, results


def _bench_pool_persistent(n: int, max_workers: int) -> tuple[float, list[float]]:
    """ProcessPoolExecutor with spawn context — workers reused across all fits.

    This is the proposed pattern. Workers pay the import cost ONCE at pool
    startup, then process N fits in parallel.
    """
    ctx = multiprocessing.get_context("spawn")
    t0 = time.perf_counter()
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as ex:
        results = list(ex.map(_fit_once, range(n)))
    return time.perf_counter() - t0, results


def _peak_rss_during(fn: Callable[[], tuple[float, list[float]]]) -> tuple[float, list[float], int]:
    """Run fn while sampling parent + all descendants' total RSS once per 100ms."""
    parent = psutil.Process(os.getpid())
    peak_rss = parent.memory_info().rss
    stop = threading.Event()

    def sampler() -> None:
        nonlocal peak_rss
        while not stop.is_set():
            try:
                rss = parent.memory_info().rss
                for child in parent.children(recursive=True):
                    try:
                        rss += child.memory_info().rss
                    except psutil.NoSuchProcess, psutil.AccessDenied:
                        pass
                if rss > peak_rss:
                    peak_rss = rss
            except psutil.NoSuchProcess:
                pass
            time.sleep(0.1)

    t = threading.Thread(target=sampler, daemon=True)
    t.start()
    try:
        elapsed, results = fn()
    finally:
        stop.set()
        t.join(timeout=1.0)
    return elapsed, results, peak_rss


def _format_rss(bytes_: int) -> str:
    mb = bytes_ / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.0f} MB"


def main() -> None:
    print(f"\nBenchmark: N={N_FITS} pyeq3 polynomial fits across four modes")
    print(f"CPU count: {multiprocessing.cpu_count()}")
    print(f"Available RAM: {_format_rss(psutil.virtual_memory().available)}\n")

    print("Warming up pyeq3 import in parent...")
    sanity = _fit_once(0)
    print(f"  one-fit sanity: {sanity:.6f}\n")

    print(f"{'mode':<22}{'wall (s)':>12}{'speedup':>10}{'peak RSS':>14}")
    print("-" * 60)

    serial_time, serial_results, serial_rss = _peak_rss_during(lambda: _bench_serial(N_FITS))
    print(f"{'serial':<22}{serial_time:>12.2f}{1.00:>10.2f}x{_format_rss(serial_rss):>14}")
    sys.stdout.flush()

    thr_time, thr_results, thr_rss = _peak_rss_during(lambda: _bench_threaded(N_FITS, N_WORKERS))
    print(
        f"{'threaded (' + str(N_WORKERS) + ' threads)':<22}{thr_time:>12.2f}"
        f"{serial_time / thr_time:>10.2f}x{_format_rss(thr_rss):>14}"
    )
    sys.stdout.flush()

    sf_time, sf_results, sf_rss = _peak_rss_during(lambda: _bench_spawn_fresh(N_FITS, N_WORKERS))
    print(
        f"{'spawn-fresh (' + str(N_WORKERS) + ' procs)':<22}{sf_time:>12.2f}"
        f"{serial_time / sf_time:>10.2f}x{_format_rss(sf_rss):>14}"
    )
    sys.stdout.flush()

    pp_time, pp_results, pp_rss = _peak_rss_during(
        lambda: _bench_pool_persistent(N_FITS, N_WORKERS)
    )
    print(
        f"{'pool-persistent (' + str(N_WORKERS) + ')':<22}{pp_time:>12.2f}"
        f"{serial_time / pp_time:>10.2f}x{_format_rss(pp_rss):>14}"
    )
    sys.stdout.flush()

    print()
    print("Result sanity check (all four should agree to ~6 decimal places):")
    print(f"  serial[0]:           {serial_results[0]:.6f}")
    print(f"  threaded[0]:         {thr_results[0]:.6f}")
    print(f"  spawn-fresh[0]:      {sf_results[0]:.6f}")
    print(f"  pool-persistent[0]:  {pp_results[0]:.6f}")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
