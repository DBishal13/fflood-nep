import numpy as np

from fflood_nep import change_detection as cd


def test_to_db_converts_linear_power_and_flags_nodata():
    gamma0 = np.array([[0.1, 1.0], [-32768.0, 0.0]], dtype=np.float32)
    db = cd.to_db(gamma0, nodata=-32768.0)
    assert db[0, 0] == np.float32(10.0 * np.log10(0.1))
    assert db[0, 1] == np.float32(0.0)
    assert db[1, 0] == cd.NODATA_DB
    assert db[1, 1] == cd.NODATA_DB


def test_speckle_filter_smooths_a_single_pixel_spike():
    db = np.zeros((5, 5), dtype=np.float32)
    db[2, 2] = 100.0
    filtered = cd.speckle_filter(db, size=3)
    assert filtered[2, 2] == 0.0


def test_flood_mask_flags_large_backscatter_drops():
    pre_db = np.array([[-5.0, -5.0]], dtype=np.float32)
    post_db = np.array([[-10.0, -5.5]], dtype=np.float32)
    mask = cd.flood_mask(pre_db, post_db, threshold_db=-3.0)
    assert mask.tolist() == [[True, False]]


def test_remove_permanent_water_drops_pre_existing_water_pixels():
    mask = np.array([[True, True]])
    worldcover = np.array([[80, 10]])
    result = cd.remove_permanent_water(mask, worldcover, water_code=80)
    assert result.tolist() == [[False, True]]


def test_polygonize_returns_area_and_confidence_for_flooded_region():
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    pre_db = np.full((4, 4), -5.0, dtype=np.float32)
    post_db = np.full((4, 4), -10.0, dtype=np.float32)
    transform = (10.0, 0.0, 0.0, 0.0, -10.0, 0.0)
    from affine import Affine

    affine_transform = Affine(*transform)

    gdf = cd.polygonize(mask, affine_transform, "EPSG:32645", pre_db, post_db)

    assert len(gdf) == 1
    assert gdf["area_m2"].iloc[0] == 400.0
    assert gdf["confidence"].iloc[0] == 5.0
