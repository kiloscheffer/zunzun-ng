"""Tests for ZUNZUN_MAX_WORKERS env var precedence and resolve_max_workers logic.

resolve_max_workers picks a worker count using:
  explicit arg > ZUNZUN_MAX_WORKERS env > settings.MAX_PARALLEL_WORKERS > auto-detect
then clamps to min(value, cpu_count, available_RAM_KiB / 200_000).
"""

import multiprocessing
import os
from unittest import mock

import pytest


def test_resolve_explicit_arg_wins_over_env(monkeypatch):
    monkeypatch.setenv("ZUNZUN_MAX_WORKERS", "32")
    # Pin hardware ceiling high so the test is portable across host machines
    fake_vmem = mock.MagicMock(available=16 * 1024**3)  # 16 GB available
    with (
        mock.patch("zunzun.parallel_pool.psutil.virtual_memory", return_value=fake_vmem),
        mock.patch("zunzun.parallel_pool.multiprocessing.cpu_count", return_value=16),
    ):
        from zunzun.parallel_pool import resolve_max_workers

        # Explicit 2 should override env var (subject to hardware ceiling)
        n = resolve_max_workers(explicit=2)
        assert n == 2


def test_resolve_env_var_wins_over_setting(monkeypatch):
    monkeypatch.setenv("ZUNZUN_MAX_WORKERS", "3")
    # Pin hardware ceiling high so the test is portable across host machines
    fake_vmem = mock.MagicMock(available=16 * 1024**3)  # 16 GB available
    with (
        mock.patch("zunzun.parallel_pool.psutil.virtual_memory", return_value=fake_vmem),
        mock.patch("zunzun.parallel_pool.multiprocessing.cpu_count", return_value=16),
        mock.patch("settings.MAX_PARALLEL_WORKERS", 7, create=True),
    ):
        from zunzun.parallel_pool import resolve_max_workers

        n = resolve_max_workers()
        assert n == 3


def test_resolve_setting_wins_over_autodetect(monkeypatch):
    monkeypatch.delenv("ZUNZUN_MAX_WORKERS", raising=False)
    # Pin hardware ceiling high so the test is portable across host machines
    fake_vmem = mock.MagicMock(available=16 * 1024**3)  # 16 GB available
    with (
        mock.patch("zunzun.parallel_pool.psutil.virtual_memory", return_value=fake_vmem),
        mock.patch("zunzun.parallel_pool.multiprocessing.cpu_count", return_value=16),
        mock.patch("settings.MAX_PARALLEL_WORKERS", 2, create=True),
    ):
        from zunzun.parallel_pool import resolve_max_workers

        n = resolve_max_workers()
        assert n == 2


def test_resolve_autodetect_returns_at_least_one(monkeypatch):
    monkeypatch.delenv("ZUNZUN_MAX_WORKERS", raising=False)
    with mock.patch("settings.MAX_PARALLEL_WORKERS", None, create=True):
        from zunzun.parallel_pool import resolve_max_workers

        n = resolve_max_workers()
        assert n >= 1
        assert n <= multiprocessing.cpu_count()


def test_resolve_clamps_to_cpu_count(monkeypatch):
    monkeypatch.setenv("ZUNZUN_MAX_WORKERS", "9999")
    from zunzun.parallel_pool import resolve_max_workers

    n = resolve_max_workers()
    assert n <= multiprocessing.cpu_count()


def test_resolve_clamps_explicit_to_cpu_count(monkeypatch):
    monkeypatch.delenv("ZUNZUN_MAX_WORKERS", raising=False)
    from zunzun.parallel_pool import resolve_max_workers

    n = resolve_max_workers(explicit=9999)
    assert n <= multiprocessing.cpu_count()


def test_resolve_invalid_env_var_falls_through(monkeypatch):
    monkeypatch.setenv("ZUNZUN_MAX_WORKERS", "not-an-integer")
    # Pin hardware ceiling high so the test is portable across host machines
    fake_vmem = mock.MagicMock(available=16 * 1024**3)  # 16 GB available
    with (
        mock.patch("zunzun.parallel_pool.psutil.virtual_memory", return_value=fake_vmem),
        mock.patch("zunzun.parallel_pool.multiprocessing.cpu_count", return_value=16),
        mock.patch("settings.MAX_PARALLEL_WORKERS", 2, create=True),
    ):
        from zunzun.parallel_pool import resolve_max_workers

        # Invalid env var ignored; falls through to settings (=2)
        n = resolve_max_workers()
        assert n == 2


def test_resolve_zero_env_var_falls_through(monkeypatch):
    monkeypatch.setenv("ZUNZUN_MAX_WORKERS", "0")
    # Pin hardware ceiling high so the test is portable across host machines
    fake_vmem = mock.MagicMock(available=16 * 1024**3)  # 16 GB available
    with (
        mock.patch("zunzun.parallel_pool.psutil.virtual_memory", return_value=fake_vmem),
        mock.patch("zunzun.parallel_pool.multiprocessing.cpu_count", return_value=16),
        mock.patch("settings.MAX_PARALLEL_WORKERS", 2, create=True),
    ):
        from zunzun.parallel_pool import resolve_max_workers

        # Zero is treated as "no override"; falls through to settings (=2)
        n = resolve_max_workers()
        assert n == 2


def test_resolve_negative_env_var_falls_through(monkeypatch):
    monkeypatch.setenv("ZUNZUN_MAX_WORKERS", "-5")
    # Pin hardware ceiling high so the test is portable across host machines
    fake_vmem = mock.MagicMock(available=16 * 1024**3)  # 16 GB available
    with (
        mock.patch("zunzun.parallel_pool.psutil.virtual_memory", return_value=fake_vmem),
        mock.patch("zunzun.parallel_pool.multiprocessing.cpu_count", return_value=16),
        mock.patch("settings.MAX_PARALLEL_WORKERS", 2, create=True),
    ):
        from zunzun.parallel_pool import resolve_max_workers

        n = resolve_max_workers()
        assert n == 2


def test_resolve_clamps_to_mem_budget(monkeypatch):
    """If available RAM is tiny, even a high env var is clamped down."""
    monkeypatch.setenv("ZUNZUN_MAX_WORKERS", "64")
    fake_vmem = mock.MagicMock(
        available=400_000 * 1024
    )  # 400_000 KiB → 2 workers @ 200_000 KiB each
    with mock.patch("zunzun.parallel_pool.psutil.virtual_memory", return_value=fake_vmem):
        from zunzun.parallel_pool import resolve_max_workers

        n = resolve_max_workers()
        assert 1 <= n <= 2
