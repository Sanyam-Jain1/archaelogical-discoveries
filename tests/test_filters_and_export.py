import xml.etree.ElementTree as ET

import numpy as np

from moundfinder.export import write_gpx, write_kml
from moundfinder.geo import BorderDistance, haversine_m, one_degree_tiles
from moundfinder.knownsites import KnownSite, match
from moundfinder.scoring import spectral
from moundfinder.sentinel2 import disc_ring_contrast


def test_haversine_one_degree_latitude():
    assert abs(haversine_m(29, 74, 30, 74) - 111_195) < 200


def test_tiles_cover_bounds():
    assert one_degree_tiles((73.2, 28.2, 75.4, 29.6)) == [
        "N28E073", "N28E074", "N28E075", "N29E073", "N29E074", "N29E075",
    ]


def test_known_site_match_uses_radius_and_precision():
    site = KnownSite("Kalibangan", 29.4729, 74.1305, radius_m=500, precision_m=500)
    hit, d = match(29.4729, 74.1405, [site], margin_m=0)  # ~970 m east
    assert hit is site and 900 < d < 1000
    miss, _ = match(29.4729, 74.1505, [site], margin_m=0)  # ~1.9 km east
    assert miss is None


def test_border_distance():
    bd = BorderDistance("config/india_pakistan_border.geojson")
    # Kalibangan is well inside India; Anupgarh sits close to the border.
    assert bd.km(74.1305, 29.4729) > 50
    assert bd.km(73.21, 29.19) < 25


def test_disc_ring_contrast_sees_bright_disc():
    img = np.full((121, 121), 0.2, dtype=float)
    img += np.random.default_rng(0).normal(0, 0.01, img.shape)
    yy, xx = np.mgrid[:121, :121]
    img[np.hypot(yy - 60, xx - 60) <= 8] += 0.1
    inner, ring, z = disc_ring_contrast(img, inner_m=60, ring_m=(120, 400))
    assert inner > ring and z > 3


def test_spectral_uses_ndvi_only_in_farmland():
    desert = {"crop_ndvi_z": -4.0, "crop_ndvi_ring": 0.1, "dry_bright_z": 0.0, "dry_bsi_z": 0.0}
    farm = dict(desert, crop_ndvi_ring=0.5)
    assert spectral(desert) == 0
    assert spectral(farm) > 0.8
    assert spectral({}) is None


def test_kml_and_gpx_are_valid_xml(tmp_path):
    cands = [{
        "id": "N29E074-00001", "score": 0.8, "summit_lat": 29.47, "summit_lon": 74.13,
        "peak_relief_m": 8.5, "area_ha": 14.0, "elongation": 1.4, "flags": "",
    }]
    write_kml(cands, tmp_path / "a.kml")
    write_gpx(cands, tmp_path / "a.gpx")
    kml = ET.parse(tmp_path / "a.kml").getroot()
    gpx = ET.parse(tmp_path / "a.gpx").getroot()
    assert len(kml.findall(".//{http://www.opengis.net/kml/2.2}Placemark")) == 1
    assert gpx.find("{http://www.topografix.com/GPX/1/1}wpt").get("lat") == "29.470000"
