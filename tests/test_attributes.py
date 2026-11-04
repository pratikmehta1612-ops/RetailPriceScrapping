import pytest

from app.extract.attributes import analyze, display_value, fix_slug_fractions, format_inches, measurements
from app.reference import Reference, build_queries, clean_title, slug_title

HUSKY = 'Husky Round Bar Hitch W/ Sway Control, 12K, 2-5/16" Ball, No Shank'


def test_husky_reference():
    category, a = analyze(HUSKY)
    assert category == "weight_distribution_hitch"
    assert a["weight_rating_lb"] == 12000
    assert a["ball_diameter_in"] == pytest.approx(2.3125)
    assert a["sway_control"] is True
    assert a["shank_included"] is False
    assert a["bar_type"] == "round bar"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("CURT TruTrack Weight Distribution Hitch with Sway Control, 8K - 12K, 2-5/16-Inch Ball",
         {"weight_rating_lb": 12000, "ball_diameter_in": 2.3125}),
        ("Fastway e2 Round Bar Hitch 12,000 lbs GTW, 1,200 lbs TW, 2\" Shank",
         {"weight_rating_lb": 12000, "tongue_weight_lb": 1200, "receiver_size_in": 2}),
        ("Equal-i-zer 4-Point Sway Control Hitch, 10,000 lbs Trailer Weight, 1,000 lbs Tongue Weight",
         {"weight_rating_lb": 10000, "tongue_weight_lb": 1000}),
        ("Pro Series Weight Distribution Kit, 5,000-10,000 lb", {"weight_rating_lb": 10000}),
        ("3 Ton Low Profile Floor Jack", {"weight_rating_lb": 6000}),
        ("Camco RV Ramp 48 inch x 24 in x 3 in", {"dimensions_in": [48, 24, 3]}),
        ("Torque Wrench 20-150 ft-lb, 1/2 in Drive", {"torque_ftlb": 150}),
        ("Hitch Pin 5/8\" Diameter", {"diameter_in": 0.625}),
        ("Receiver Hitch Class III, 2 in. Receiver, 6,000 lb", {"class": 3, "receiver_size_in": 2, "weight_rating_lb": 6000}),
    ],
)
def test_measurements(title, expected):
    attrs = measurements(title)
    for key, value in expected.items():
        assert attrs[key] == pytest.approx(value), (key, attrs)


def test_4k_dash_cam_is_not_a_weight():
    assert "weight_rating_lb" not in measurements("Nextbase 622GW 4K Dash Cam")


def test_slug_and_titles():
    url = ("https://www.overtons.com/husky-round-bar-weight-distribution-hitch-with-sway-control-"
           "12k-2-516-ball-no-shank-146894.html?utm_source=bing")
    assert slug_title(url) == "husky round bar weight distribution hitch with sway control 12k 2-5/16 ball no shank"
    assert fix_slug_fractions("2 12 ball") == "2-1/2 ball"
    assert clean_title(HUSKY + " | Overton's") == HUSKY
    assert clean_title("Amazon.com: CURT 45810 Ball Mount") == "CURT 45810 Ball Mount"


def test_display():
    assert format_inches(2.3125) == '2-5/16"'
    assert format_inches(2.0) == '2"'
    assert display_value("weight_rating_lb", 12000.0) == "12,000 lb"
    assert display_value("sway_control", True) == "yes"


def test_queries_cover_exact_and_brand_free():
    category, attrs = analyze(HUSKY)
    ref = Reference(title=HUSKY, brand="Husky", category=category, attributes=attrs)
    queries = build_queries(ref, 3)
    assert queries[0].startswith("Husky Round Bar Hitch with Sway Control 12K 2-5/16")
    assert "husky" not in queries[1].lower()
    assert "12000 lb" in queries[1] and "2-5/16 ball" in queries[1]
    assert len(queries) == 3
