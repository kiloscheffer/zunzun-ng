"""Unit tests for 3D animation GIF generation.

Both animation classes (ScatterAnimation, SurfaceAnimation) build a
matplotlib 3D figure, rotate the camera through 360°, and write an
animated GIF to disk. These tests drive each class end-to-end with a
minimal DataObject, and assert the produced file is a valid multi-frame
animated GIF.

No Django, no spawn, no session DB — just matplotlib + Pillow.
"""
import os

import numpy
import pytest
from PIL import Image

from zunzun.LongRunningProcess import ReportsAndGraphs
from zunzun.LongRunningProcess.DataObject import DataObject


def _build_3d_dataobject(tmp_path):
    """Minimal DataObject for a 3D animation test.

    Hand-populates the attributes the animation classes actually read,
    using a small synthetic dataset. 12-point 3D grid with smooth Z
    values is enough for matplotlib to render a visible scatter/surface.
    """
    obj = DataObject()
    obj.dimensionality = 3
    obj.animationHeight = 240
    obj.animationWidth = 320
    obj.graphHeight = 240
    obj.graphWidth = 320
    obj.altimuth3D = 20  # sic: typo pre-existing in production (MatplotlibGraphs_3D reads both altimuth3D and azimuth3D)
    obj.azimuth3D = 45
    obj.uniqueString = "testanim"

    # 12-point 3D grid: X,Y each spans three values, Z = X + 2*Y
    x = numpy.array([1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 3.0, 3.0, 3.0, 4.0, 4.0, 4.0])
    y = numpy.array([1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 1.0, 2.0, 3.0])
    z = x + 2.0 * y

    obj.IndependentDataArray = numpy.array([x, y])
    obj.DependentDataArray = z

    # Graph-boundary attributes (normally computed by CalculateGraphBoundaries)
    obj.minX, obj.maxX = float(x.min()), float(x.max())
    obj.minY, obj.maxY = float(y.min()), float(y.max())
    obj.minZ, obj.maxZ = float(z.min()), float(z.max())

    # Populate obj.statistics with '1_min'/'1_max', '2_min'/'2_max',
    # '3_min'/'3_max' — the animation classes call CalculateGraphBoundaries()
    # internally, which reads these keys.
    obj.CalculateDataStatistics()

    return obj


@pytest.fixture
def settings_temp_dir(tmp_path, settings):
    """Point settings.TEMP_FILES_DIR and STATIC_URL at a pytest tmp_path."""
    settings.TEMP_FILES_DIR = str(tmp_path)
    settings.STATIC_URL = "/temp/"
    return tmp_path


@pytest.mark.django_db
def test_scatter_animation_produces_valid_gif(settings_temp_dir):
    """ScatterAnimation renders a rotating 3D scatter GIF."""
    dataobject = _build_3d_dataobject(settings_temp_dir)

    animation = ReportsAndGraphs.ScatterAnimation(dataobject)
    animation.animationFrameSeparation = 60  # 6 frames for fast test
    animation.PrepareForCharacterizerOutput()

    assert animation.physicalFileLocation, \
        "PrepareForCharacterizerOutput did not set physicalFileLocation"

    animation.CreateCharacterizerOutput()

    assert os.path.exists(animation.physicalFileLocation), \
        f"GIF not created at {animation.physicalFileLocation}"

    with Image.open(animation.physicalFileLocation) as img:
        assert img.format == "GIF", f"Expected GIF, got {img.format}"
        assert img.n_frames >= 2, f"Expected ≥2 frames, got {img.n_frames}"


@pytest.mark.django_db
def test_surface_animation_produces_valid_gif(settings_temp_dir):
    """SurfaceAnimation renders a rotating 3D fitted-surface GIF.

    Requires the DataObject's equation to have solved coefficients. We
    stub a 3D Linear polynomial (Z = a + b*X + c*Y) with known values.
    """
    import pyeq3
    dataobject = _build_3d_dataobject(settings_temp_dir)

    equation = pyeq3.Models_3D.Polynomial.Linear()
    equation.solvedCoefficients = numpy.array([0.0, 1.0, 2.0])  # matches Z=X+2Y
    equation.dataCache = pyeq3.dataCache()
    equation.dataCache.independentData = dataobject.IndependentDataArray
    equation.dataCache.dependentData = dataobject.DependentDataArray
    dataobject.equation = equation

    animation = ReportsAndGraphs.SurfaceAnimation(dataobject)
    animation.animationFrameSeparation = 60
    animation.PrepareForReportOutput()

    assert animation.physicalFileLocation, \
        "PrepareForReportOutput did not set physicalFileLocation"

    animation.CreateReportOutput()

    assert os.path.exists(animation.physicalFileLocation), \
        f"GIF not created at {animation.physicalFileLocation}"

    with Image.open(animation.physicalFileLocation) as img:
        assert img.format == "GIF"
        assert img.n_frames >= 2
