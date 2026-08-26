from fflood_nep import pc_client


class FakeAsset:
    def __init__(self, href: str):
        self.href = href


class FakeItem:
    def __init__(self, assets: dict):
        self.assets = assets


REAL_STYLE_PREVIEW_HREF = (
    "https://planetarycomputer.microsoft.com/api/data/v1/item/preview.png"
    "?collection=sentinel-1-rtc&item=S1D_IW_GRDH_1SDV_20260824T001844_20260824T001909_004260_007D5D_rtc"
    "&assets=vv&assets=vh&tile_format=png&expression=some+expression"
    "&asset_as_band=True&rescale=0%2C.8000&rescale=0%2C1.000&rescale=0%2C1.000&format=png"
)


def test_preview_url_crops_to_bbox_instead_of_the_whole_scene():
    item = FakeItem({"rendered_preview": FakeAsset(REAL_STYLE_PREVIEW_HREF)})
    bbox = (85.10, 27.85, 85.75, 28.45)

    url = pc_client.preview_url(item, bbox)

    from urllib.parse import parse_qsl, urlsplit

    assert url.startswith("https://planetarycomputer.microsoft.com/api/data/v1/item/bbox/85.1,27.85,85.75,28.45.png?")
    query = parse_qsl(urlsplit(url).query)
    assert query.count(("assets", "vv")) == 1  # repeated keys must survive the round-trip,
    assert query.count(("assets", "vh")) == 1  # not collapse to just the last occurrence
    assert [v for k, v in query if k == "rescale"] == ["0,.8000", "0,1.000", "0,1.000"]
    assert ("collection", "sentinel-1-rtc") in query
    assert ("item", "S1D_IW_GRDH_1SDV_20260824T001844_20260824T001909_004260_007D5D_rtc") in query
    assert ("expression", "some expression") in query
    assert ("max_size", "1024") in query
    assert "tile_format" not in url  # dropped: irrelevant to the bbox endpoint


def test_preview_url_is_none_without_a_rendered_preview_asset():
    item = FakeItem({})
    assert pc_client.preview_url(item, (85.10, 27.85, 85.75, 28.45)) is None
