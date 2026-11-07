import io

import pytest
from PIL import Image

from services.investigate import InvestigationValidationError, investigate_image
from tools.image_intel import analyze_image, gps_coordinates, reverse_image_links


class Ratio:
    def __init__(self, num: int, den: int) -> None:
        self.num = num
        self.den = den


class Tag:
    def __init__(self, values) -> None:
        self.values = values


def test_gps_coordinates_are_converted_to_decimal():
    tags = {
        "GPS GPSLatitude": Tag([Ratio(40, 1), Ratio(26, 1), Ratio(46, 3)]),
        "GPS GPSLongitude": Tag([Ratio(79, 1), Ratio(58, 1), Ratio(56, 1)]),
        "GPS GPSLatitudeRef": "N",
        "GPS GPSLongitudeRef": "E",
    }

    assert gps_coordinates(tags) == (40.437593, 79.982222)


def test_gps_coordinates_south_west_are_negative():
    tags = {
        "GPS GPSLatitude": Tag([Ratio(10, 1), Ratio(0, 1), Ratio(0, 1)]),
        "GPS GPSLongitude": Tag([Ratio(20, 1), Ratio(0, 1), Ratio(0, 1)]),
        "GPS GPSLatitudeRef": "S",
        "GPS GPSLongitudeRef": "W",
    }

    assert gps_coordinates(tags) == (-10.0, -20.0)


def test_reverse_image_links_encode_the_source_url():
    links = reverse_image_links("https://example.com/a b.jpg")

    assert "https://lens.google.com/uploadbyurl?url=https%3A%2F%2Fexample.com%2Fa%20b.jpg" == links["Google Lens"]
    assert set(links) == {"Google Lens", "Yandex", "TinEye", "Bing Visual Search"}


def test_analyze_image_reports_dimensions_and_reverse_links():
    buffer = io.BytesIO()
    Image.new("RGB", (10, 20), "red").save(buffer, format="PNG")

    outcome = analyze_image(buffer.getvalue(), "https://example.com/x.png")
    platforms = [item["platform"] for item in outcome["results"]]

    assert "Image info" in platforms
    assert any(platform.startswith("Reverse image:") for platform in platforms)
    info = next(
        item["info"] for item in outcome["results"] if item["platform"] == "Image info"
    )
    assert "10x20" in info


async def test_investigate_image_rejects_non_http_url():
    with pytest.raises(InvestigationValidationError):
        await investigate_image("ftp://example.com/photo.jpg")
