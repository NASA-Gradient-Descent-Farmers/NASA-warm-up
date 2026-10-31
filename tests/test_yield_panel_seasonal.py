"""Offline checks for seasonal.py (GEOS-S2S April forecasts) using tiny synthetic NetCDF files."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy.io import netcdf_file

from src.yield_panel import seasonal


def write(path, var, starts, values, with_z=False):
    """starts: months since 1960-01; values: (S, L, Y, X)."""
    f = netcdf_file(path, "w")
    leads = np.array([0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5])
    dims = [("S", len(starts)), ("L", 7)] + ([("Z", 1)] if with_z else []) + [("Y", 2), ("X", 2)]
    for name, n in dims:
        f.createDimension(name, n)
    for name, data in [("S", np.array(starts, float)), ("L", leads), ("Y", np.array([19.0, 20.0])),
                       ("X", np.array([259.0, 260.0]))] + ([("Z", np.array([2.0]))] if with_z else []):
        v = f.createVariable(name, "d", (name,))
        v[:] = data
    v = f.createVariable(var, "d", tuple(n for n, _ in dims))
    v[:] = values.reshape([d for _, d in dims])
    f.close()


class TestSeasonal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        # Hindcast: April starts 1991-2016 plus a May start that must be ignored. Forecast: April 2017-2018.
        apr = lambda y: (y - 1960) * 12 + 3
        h_starts = [apr(y) for y in range(1991, 2017)] + [apr(2000) + 1]
        f_starts = [apr(2017), apr(2018)]
        base = np.ones((1, 7, 2, 2))  # 1 mm/day everywhere, every lead
        h = np.repeat(base, len(h_starts), axis=0)
        h[-1] = 99.0  # the May start: must not enter the climatology
        fc = np.repeat(base, 2, axis=0)
        fc[1, 1:] = 2.0  # 2018: 1 mm/day wetter than usual from May to October
        write(d / "prec_HINDCAST_mex.nc", "prec", h_starts, h)
        write(d / "prec_FORECAST_mex.nc", "prec", f_starts, fc)
        t = np.repeat(base * 290.0, len(h_starts), axis=0)
        write(d / "tref_HINDCAST_mex.nc", "tref", h_starts, t, with_z=True)
        tf = np.repeat(base * 290.0, 2, axis=0)
        tf[1] += 1.5
        write(d / "tref_FORECAST_mex.nc", "tref", f_starts, tf, with_z=True)
        self.dir = d

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_april_starts_and_streams_joined(self):
        years, cube, lat, lon, leads = seasonal.april_forecasts("prec", self.dir)
        self.assertEqual(list(years), list(range(1991, 2019)))
        self.assertEqual(cube.shape, (28, 7, 2, 2))
        self.assertTrue((lon < 0).all())  # 0-360 converted to -180..180

    def test_anomalies_and_period_totals(self):
        self.assertEqual(seasonal.available(self.dir), ["prec", "tref"])
        years, grids, lat, lon = seasonal.anomaly_grids(self.dir)
        i = list(years).index(2018)
        days_may_oct = 31 + 30 + 31 + 31 + 30 + 31
        self.assertAlmostEqual(grids["s2s_prec_may_oct_anom_mm"][i, 0, 0], days_may_oct)
        self.assertAlmostEqual(grids["s2s_prec_jul_aug_anom_mm"][i, 0, 0], 62.0)
        self.assertAlmostEqual(grids["s2s_prec_jun_anom_mm"][i, 0, 0], 30.0)
        self.assertAlmostEqual(grids["s2s_tref_may_oct_anom_c"][i, 0, 0], 1.5)
        j = list(years).index(2017)
        self.assertAlmostEqual(grids["s2s_prec_may_oct_anom_mm"][j, 0, 0], 0.0)


if __name__ == "__main__":
    unittest.main()
