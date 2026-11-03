"""The WOFOST / NSGA side (src/crop_models) and the rotation tool (src/rotations) must describe the same crops.

They were built separately. These checks fail if one side renames a crop or a rotation, or reads a different
SIAP crop, so the two can be joined (docs/planner_vs_rotation_tool.md).
"""

import unittest

from src.crop_models.farm_tool import SIAP_CROPS
from src.crop_models.wofost_rotations import ROTATIONS
from src.rotations import candidates, catalog


class TestSharedVocabulary(unittest.TestCase):
    def test_every_planner_rotation_parses_in_the_rotation_tool(self):
        for name, crops in ROTATIONS.items():
            parsed = candidates.parse_rotation(name)
            self.assertEqual([next(iter(year.values())) for year in parsed],
                             [candidates.crop_key(crop) for crop in crops], name)
            self.assertTrue(all(set(year) == {"pv"} for year in parsed), name)   # spring-summer, as in WOFOST

    def test_both_sides_read_the_same_siap_crop_names(self):
        for planner_key, siap_name in SIAP_CROPS.items():
            tool_key = candidates.crop_key(planner_key)
            self.assertEqual(catalog.plain(catalog.crops().loc[tool_key, "siap"]), catalog.plain(siap_name),
                             planner_key)


if __name__ == "__main__":
    unittest.main()
