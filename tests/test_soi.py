import numpy as np
import pytest

from moundfinder.soi import MOUND_TERMS, Sheet, find_frame, parse_name, sheet_bounds


def test_sheet_numbering_matches_printed_corners():
    # 44 K/13 is printed with corners 74 45'-75 00' E, 29 45'-30 00' N (surveyed 1912-13).
    assert sheet_bounds("44", "K", 13) == (74.75, 29.75, 75.0, 30.0)
    # 44 A is the north-west degree sheet of block 44 (Jhang district).
    assert sheet_bounds("44", "A", 1) == (72.0, 31.75, 72.25, 32.0)
    assert sheet_bounds("44", "P", 16) == (75.75, 28.0, 76.0, 28.25)


def test_parse_names_in_both_spellings():
    assert parse_name("44 L]06 Churu District (1966).jpg") == ("44", "L", 6, 1966)
    assert parse_name("44 K 13 Hissar District (1914).jpg") == ("44", "K", 13, 1914)
    with pytest.raises(ValueError):
        parse_name("Index to Survey of India.jpg")


def test_pixel_lonlat_round_trip_on_a_rotated_scan():
    # Corners of a frame rotated by ~0.5 degrees.
    corners = ((481, 936), (5299, 978), (5251, 6487), (433, 6445))
    s = Sheet("44 K]13", None, (74.75, 29.75, 75.0, 30.0), 1914, corners=corners)
    x, y = s.to_pixel(74.8, 29.9)
    lon, lat = s.to_lonlat(x, y)
    assert abs(lon - 74.8) < 1e-6 and abs(lat - 29.9) < 1e-6
    nx, ny = s.to_pixel(74.75, 30.0)  # north-west corner
    assert abs(nx - 481) < 1e-3 and abs(ny - 936) < 1e-3


def test_find_frame_on_synthetic_sheet():
    # A 15' sheet at 29.9 N is ~0.87 times as wide as tall on the ground.
    h, w = 2000, 1800
    gray = np.full((h, w), 230, np.float32)
    top, bottom, left = 200, 1800, 150
    right = int(left + (bottom - top) * 0.25 * np.cos(np.radians(29.875)) / 0.25 * 1.0055)
    for y in (top, bottom):
        gray[y - 4:y + 5, left:right + 1] = 20
    for x in (left, right):
        gray[top:bottom + 1, x - 4:x + 5] = 20
    gray[1000, 100:1700] = 20  # a thin grid line that must not be taken for the frame
    nw, ne, se, sw = find_frame(gray, (74.75, 29.75, 75.0, 30.0))
    for (x, y), (ex, ey) in zip((nw, ne, se, sw), ((left, top), (right, top), (right, bottom), (left, bottom))):
        assert abs(x - ex) <= 6 and abs(y - ey) <= 6


def test_mound_terms():
    for t in ["Theh", "Theri Ganga", "Sanwat Khera", "Dheri", "Ruins", "Old Site", "Kheri"]:
        assert MOUND_TERMS.search(t), t
    for t in ["Kalanwali", "Hissar", "Thermal"]:
        assert not MOUND_TERMS.search(t), t


def test_label_phrases_join_name_and_term_on_one_line():
    from moundfinder.soi import label_phrases

    sheet = "44 K 03"
    words = [
        {"text": "Kalibangan", "lat": 29.4752, "lon": 74.1380, "sheet": sheet, "year": 1959, "conf": 90},
        {"text": "(ruins)", "lat": 29.4752, "lon": 74.1418, "sheet": sheet, "year": 1959, "conf": 94},
        {"text": "Pilibangan", "lat": 29.4900, "lon": 74.1418, "sheet": sheet, "year": 1959, "conf": 90},  # other line
        {"text": "(ruins)", "lat": 29.4753, "lon": 74.1419, "sheet": sheet, "year": 1959, "conf": 80},  # tile duplicate
    ]
    out = label_phrases(words)
    assert len(out) == 1
    assert out[0]["label"] == "Kalibangan (ruins)"


def test_label_kinds():
    from moundfinder.soi import label_kind

    assert label_kind("Kala Theh") == "mound"
    assert label_kind("(In ruins)") == "ruins"
    assert label_kind("ruins) ruins).") == "ruins"
    assert label_kind("Asa Khera") == "name"


def test_historical_leads_marks_recorded_sites_and_candidates():
    from moundfinder.knownsites import KnownSite
    from moundfinder.soi import historical_leads

    phrases = [{"label": "Kala Theh", "lat": 29.4730, "lon": 74.1300, "sheet": "44 K 03", "year": 1959, "conf": 90},
               {"label": "(In ruins)", "lat": 29.3000, "lon": 74.2000, "sheet": "44 K 03", "year": 1959, "conf": 90}]
    known = [KnownSite("Kalibangan", 29.4740, 74.1310, 300, 100, "test")]
    cands = [{"id": "a", "lat": 29.0, "lon": 74.0}, {"id": "b", "lat": 29.3010, "lon": 74.2005}]
    out = historical_leads(phrases, known, cands, margin_m=300)
    assert out[0]["known_site"] == "Kalibangan" and out[0]["kind"] == "mound"
    assert out[1]["known_site"] == "" and out[1]["candidate"] == "b" and out[1]["candidate_rank"] == 2
