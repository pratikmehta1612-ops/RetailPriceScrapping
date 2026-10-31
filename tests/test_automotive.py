import pytest

from app.extract.automotive import extract_features, unit_price, volume_in_quarts


def test_tire():
    cat, f = extract_features("Michelin Defender2 225/65R17 102H All-Season Tire", brand="Michelin")
    assert cat == "tire"
    assert f["tire_size"] == "225/65R17"
    assert f["tire_width_mm"] == 225 and f["aspect_ratio"] == 65 and f["rim_diameter_in"] == 17
    assert f["load_index"] == "102"
    assert f["speed_rating"] == "H"
    assert f["season"] == "all-season"


@pytest.mark.parametrize(
    "title,size,speed",
    [
        ("Pirelli P Zero 245/40ZR18 97Y XL Summer", "245/40R18", "Y"),
        ("BFGoodrich All-Terrain T/A KO2 LT265/70R17 121/118S", "265/70R17", "S"),
        ("Cooper Discoverer P235/75R15 108T", "235/75R15", "T"),
    ],
)
def test_tire_size_variants(title, size, speed):
    _, f = extract_features(title)
    assert f["tire_size"] == size
    assert f["speed_rating"] == speed


def test_motor_oil():
    cat, f = extract_features(
        "Mobil 1 Extended Performance Full Synthetic Motor Oil 5W-30, 5 Quart",
        "Meets API SP and ILSAC GF-6. dexos1 approved",
    )
    assert cat == "motor_oil"
    assert f["viscosity"] == "5W-30"
    assert f["oil_type"] == "full synthetic"
    assert f["volume_quarts"] == 5
    assert "API SP" in f["approvals"]


def test_oil_multipack_unit_price():
    cat, f = extract_features("Castrol GTX High Mileage 10W-40 Motor Oil 1 Quart, Pack of 6")
    assert f["oil_type"] == "high mileage"
    assert f["volume_quarts"] == 6
    assert unit_price(cat, f, 41.94) == (6.99, "quart")


def test_battery():
    cat, f = extract_features("EverStart Platinum AGM Automotive Battery, Group Size H6 12 Volt, 760 CCA")
    assert cat == "battery"
    assert f["group_size"] == "H6"
    assert f["cca"] == 760
    assert f["chemistry"] == "AGM"
    assert f["voltage"] == 12


def test_wiper():
    cat, f = extract_features("Bosch ICON 22A Beam Wiper Blade, 22 Inch")
    assert cat == "wiper_blade"
    assert f["blade_length_in"] == 22
    assert f["blade_style"] == "beam"


def test_bulb_and_fitment():
    cat, f = extract_features("SYLVANIA H11 SilverStar Ultra Halogen Headlight Bulb for 2015-2020 Ford F-150")
    assert cat == "headlight_bulb"
    assert f["bulb_code"] == "H11"
    assert f["bulb_tech"] == "halogen"
    assert f["fits_makes"] == ["Ford"]
    assert f["fits_years"] == [2015, 2020]


def test_brake_pads():
    cat, f = extract_features("Power Stop Z23 Evolution Ceramic Front Brake Pads for 2019 Honda Civic")
    assert cat == "brake_pads"
    assert f["pad_material"] == "ceramic"
    assert f["position"] == "front"
    assert f["fits_years"] == [2019, 2019]


def test_specs_fill_gaps():
    cat, f = extract_features(
        "Valvoline Advanced Full Synthetic Motor Oil",
        specs={"Viscosity": "0W-20", "Capacity (Volume)": "5 Quart"},
    )
    assert f["viscosity"] == "0W-20"
    assert f["volume_quarts"] == 5


def test_volume_units():
    assert volume_in_quarts("1 gallon") == 4
    assert volume_in_quarts("5 L jug") == pytest.approx(5.28, abs=0.01)
    assert volume_in_quarts("12 fl oz") == pytest.approx(0.38, abs=0.01)
