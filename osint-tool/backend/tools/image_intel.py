import hashlib
import io
from urllib.parse import quote

import exifread
from PIL import Image

from tools.base import ToolError
from tools.net_guard import safe_get

MAX_IMAGE_BYTES = 15 * 1024 * 1024
IMAGE_HEADERS = {"User-Agent": "osint-tool/1.0 (local self-audit)"}

EXIF_FIELDS = [
    ("Image Make", "Camera make"),
    ("Image Model", "Camera model"),
    ("EXIF LensModel", "Lens"),
    ("EXIF DateTimeOriginal", "Taken"),
    ("Image Software", "Software"),
    ("Image Orientation", "Orientation"),
]


def _to_float(value) -> float:
    num = getattr(value, "num", None)
    den = getattr(value, "den", None)
    if num is not None and den not in (None, 0):
        return float(num) / float(den)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def gps_coordinates(tags: dict) -> tuple[float, float] | None:
    latitude = tags.get("GPS GPSLatitude")
    longitude = tags.get("GPS GPSLongitude")
    if not latitude or not longitude:
        return None
    try:
        lat_values = [_to_float(value) for value in latitude.values]
        lon_values = [_to_float(value) for value in longitude.values]
    except AttributeError:
        return None
    if len(lat_values) < 3 or len(lon_values) < 3:
        return None

    lat = lat_values[0] + lat_values[1] / 60 + lat_values[2] / 3600
    lon = lon_values[0] + lon_values[1] / 60 + lon_values[2] / 3600
    lat_ref = str(tags.get("GPS GPSLatitudeRef", "N")).strip().upper()
    lon_ref = str(tags.get("GPS GPSLongitudeRef", "E")).strip().upper()
    if lat_ref.startswith("S"):
        lat = -lat
    if lon_ref.startswith("W"):
        lon = -lon
    return round(lat, 6), round(lon, 6)


def reverse_image_links(url: str) -> dict[str, str]:
    encoded = quote(url, safe="")
    return {
        "Google Lens": f"https://lens.google.com/uploadbyurl?url={encoded}",
        "Yandex": f"https://yandex.com/images/search?rpt=imageview&url={encoded}",
        "TinEye": f"https://tineye.com/search?url={encoded}",
        "Bing Visual Search": f"https://www.bing.com/images/search?view=detailv2&iss=sbi&form=SBIVSP&sbisrc=UrlPaste&q=imgurl:{encoded}",
    }


def analyze_image(data: bytes, url: str) -> dict:
    warnings: list[str] = []
    results: list[dict] = []

    try:
        tags = exifread.process_file(io.BytesIO(data), details=False)
    except Exception as exc:
        tags = {}
        warnings.append(f"EXIF parser failed: {exc}")

    width = height = None
    image_format = "unknown"
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image_format = image.format or "unknown"
    except Exception as exc:
        warnings.append(f"Could not decode image: {exc}")

    digest = hashlib.sha256(data).hexdigest()
    results.append(
        {
            "platform": "Image info",
            "url": url,
            "status": "found",
            "info": (
                f"Format: {image_format} | Size: {width}x{height} | "
                f"Bytes: {len(data)} | SHA-256: {digest}"
            ),
        }
    )

    metadata = []
    for tag_name, label in EXIF_FIELDS:
        value = tags.get(tag_name)
        if value:
            metadata.append(f"{label}: {value}")
    if metadata:
        results.append(
            {
                "platform": "EXIF metadata",
                "status": "found",
                "info": "; ".join(metadata),
            }
        )
    else:
        warnings.append(
            "No readable EXIF metadata found (the image may have been "
            "stripped by the platform)."
        )

    coordinates = gps_coordinates(tags)
    if coordinates:
        lat, lon = coordinates
        results.append(
            {
                "platform": "GPS location",
                "url": f"https://www.google.com/maps?q={lat},{lon}",
                "status": "found",
                "info": f"Coordinates: {lat}, {lon}",
            }
        )
        results.append(
            {
                "platform": "OpenStreetMap",
                "url": (
                    f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}"
                    f"#map=16/{lat}/{lon}"
                ),
                "status": "found",
                "info": "Open the coordinates on a community map.",
            }
        )
    else:
        warnings.append("No GPS coordinates embedded in the image.")

    for name, link in reverse_image_links(url).items():
        results.append(
            {
                "platform": f"Reverse image: {name}",
                "url": link,
                "status": "found",
                "info": "Search for other copies of this image.",
            }
        )

    return {"results": results, "warnings": warnings}


async def fetch_image_bytes(client, url: str) -> tuple[bytes, str, str]:
    response = await safe_get(client, url)
    if response.status_code != 200:
        raise ToolError(f"Image URL returned HTTP {response.status_code}.")
    if len(response.content) > MAX_IMAGE_BYTES:
        raise ToolError(
            f"Image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB."
        )
    content_type = response.headers.get("content-type", "").lower()
    if content_type and not (
        content_type.startswith("image/")
        or content_type.startswith("application/octet-stream")
    ):
        raise ToolError(
            f"URL did not return an image (content-type: {content_type})."
        )
    return response.content, content_type, str(response.url)
