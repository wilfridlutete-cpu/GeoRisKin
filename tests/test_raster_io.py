"""Tests du module engine.raster_io sur des rasters synthétiques."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import Affine

from engine.raster_io import (UTM33S, WGS84, dted_tile_origin, dted_overview_transform,
                              georeference_dted_overview, reproject_dem, dem_report)


def test_tile_origin():
    assert dted_tile_origin("DTED_E015_S05.DT2.ovr") == (15.0, -5.0)
    assert dted_tile_origin("DTED_W003_N12.DT2") == (-3.0, 12.0)
    with pytest.raises(ValueError):
        dted_tile_origin("srtm.tif")


def test_overview_transform_covers_tile_with_half_pixel_margin():
    tr = dted_overview_transform("DTED_E015_S05", 1801, 1801)
    half = 0.5 / 3600
    assert tr.c == pytest.approx(15 - half)
    assert tr.f == pytest.approx(-4 + half)
    right = tr.c + 1801 * tr.a
    bottom = tr.f + 1801 * tr.e
    assert right == pytest.approx(16 + half)
    assert bottom == pytest.approx(-5 - half)


def _write_ovr(path, arr, nodata=-32767):
    prof = dict(driver="GTiff", width=arr.shape[1], height=arr.shape[0], count=1,
                dtype="int16", nodata=nodata)
    with rasterio.open(path, "w", **prof) as d:
        d.write(arr, 1)


def test_georeference_keeps_values_and_nodata(tmp_path):
    arr = np.arange(100, dtype="int16").reshape(10, 10) + 300
    arr[0, 0] = -32767
    src = tmp_path / "DTED_E015_S05.DT2.ovr"
    _write_ovr(src, arr)
    info = georeference_dted_overview(src, tmp_path / "out.tif")
    assert info["nodata_count"] == 1
    with rasterio.open(tmp_path / "out.tif") as s:
        assert s.crs == WGS84
        assert np.array_equal(s.read(1), arr)


def test_reproject_aligned_grid_and_nodata_not_filled(tmp_path):
    # pente synthétique : z augmente vers l'est, un trou NoData au centre
    n = 200
    z = np.tile(np.linspace(300, 500, n, dtype="float32"), (n, 1))
    z[95:105, 95:105] = -9999
    src = tmp_path / "dem.tif"
    tr = Affine(0.0005, 0, 15.30, 0, -0.0005, -4.38)
    with rasterio.open(src, "w", driver="GTiff", width=n, height=n, count=1,
                       dtype="float32", crs=WGS84, transform=tr, nodata=-9999) as d:
        d.write(z, 1)
    dst = tmp_path / "utm.tif"
    reproject_dem(src, dst, UTM33S, 60.0)
    with rasterio.open(dst) as s:
        assert s.crs == UTM33S
        assert s.res == (60.0, 60.0)
        assert s.transform.c % 60 == 0 and s.transform.f % 60 == 0  # grille alignée
        out = s.read(1)
    assert np.isnan(out).any()                       # le trou reste NoData
    r = dem_report(dst)
    assert 299 <= r.z_min and r.z_max <= 501          # pas de valeurs inventées
    row = out[out.shape[0] // 4]
    v = row[~np.isnan(row)]
    assert np.all(np.diff(v) >= -1e-3)                # la pente est-ouest est conservée


def test_mosaic_of_non_gtiff_tiles_writes_gtiff(tmp_path):
    from engine.raster_io import mosaic
    paths = []
    for i, x0 in enumerate((15.0, 15.5)):
        p = tmp_path / f"t{i}.img"   # format ERDAS, comme DTED : non GeoTIFF
        tr = Affine(0.01, 0, x0, 0, -0.01, -4.0)
        with rasterio.open(p, "w", driver="HFA", width=50, height=50, count=1, dtype="int16",
                           crs=WGS84, transform=tr, nodata=-32767) as d:
            d.write(np.full((50, 50), 300 + i, "int16"), 1)
        paths.append(p)
    out = tmp_path / "m.tif"
    mosaic(paths, out)
    with rasterio.open(out) as s:
        assert s.driver == "GTiff" and s.width == 100
        a = s.read(1)
    assert (a[:, :50] == 300).all() and (a[:, 50:] == 301).all()
