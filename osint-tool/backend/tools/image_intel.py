import hashlib
import io
import datetime
import math
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


_RAD = math.pi / 180
_OBLIQUITY = _RAD * 23.4397
CARDINALS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def cardinal(bearing: float) -> str:
    return CARDINALS[round(bearing / 22.5) % 16]


def decimal_to_dms(value: float, positive: str, negative: str) -> str:
    hemisphere = positive if value >= 0 else negative
    value = abs(value)
    degrees = int(value)
    minutes_full = (value - degrees) * 60
    minutes = int(minutes_full)
    seconds = (minutes_full - minutes) * 60
    return f"{degrees}°{minutes:02d}′{seconds:04.1f}″{hemisphere}"


def sun_position(timestamp: float, lat: float, lng: float) -> tuple[float, float]:
    """Sun azimuth (compass bearing from North) and altitude in degrees (UTC)."""
    days = (timestamp / 86400 + 2440587.5) - 2451545
    mean_anomaly = _RAD * (357.5291 + 0.98560028 * days)
    ecliptic_long = (
        mean_anomaly
        + _RAD * (1.9148 * math.sin(mean_anomaly) + 0.02 * math.sin(2 * mean_anomaly)
                  + 0.0003 * math.sin(3 * mean_anomaly))
        + _RAD * 102.9372 + math.pi
    )
    declination = math.asin(math.sin(ecliptic_long) * math.sin(_OBLIQUITY))
    right_ascension = math.atan2(
        math.sin(ecliptic_long) * math.cos(_OBLIQUITY), math.cos(ecliptic_long)
    )
    lw = _RAD * -lng
    phi = _RAD * lat
    hour_angle = _RAD * (280.16 + 360.9856235 * days) - lw - right_ascension
    azimuth = math.atan2(
        math.sin(hour_angle),
        math.cos(hour_angle) * math.sin(phi) - math.tan(declination) * math.cos(phi),
    )
    altitude = math.asin(
        math.sin(phi) * math.sin(declination)
        + math.cos(phi) * math.cos(declination) * math.cos(hour_angle)
    )
    return (math.degrees(azimuth) + 180) % 360, math.degrees(altitude)


def _dms_to_float(values) -> float:
    parts = [_to_float(v) for v in values]
    while len(parts) < 3:
        parts.append(0.0)
    return parts[0] + parts[1] / 60 + parts[2] / 3600


def gps_datetime_utc(tags: dict) -> float | None:
    """Exact UTC capture time from GPS tags, if present."""
    stamp = tags.get("GPS GPSDateStamp")
    time_tag = tags.get("GPS GPSTimeStamp")
    if not stamp or not time_tag:
        return None
    try:
        year, month, day = (int(part) for part in str(stamp).replace("-", ":").split(":")[:3])
        hour, minute, second = (_to_float(v) for v in time_tag.values)
        return datetime.datetime(
            year, month, day, int(hour), int(minute), int(second),
            tzinfo=datetime.timezone.utc,
        ).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def approx_datetime_utc(tags: dict, lon: float) -> float | None:
    """Estimate UTC from DateTimeOriginal, assuming the clock shows local time.

    No embedded timezone, so the offset is guessed from longitude (~15 deg/hour).
    Good enough to sanity-check shadow direction, not for precise timing.
    """
    taken = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
    if not taken:
        return None
    try:
        naive = datetime.datetime.strptime(str(taken).strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    offset_hours = round(lon / 15)
    return (naive - datetime.timedelta(hours=offset_hours)).replace(
        tzinfo=datetime.timezone.utc
    ).timestamp()


def geo_links(lat: float, lon: float, timestamp: float | None) -> dict[str, str]:
    links = {
        "Google Maps": f"https://www.google.com/maps?q={lat},{lon}",
        "Google Street View": (
            f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}"
        ),
        "Google Earth": f"https://earth.google.com/web/@{lat},{lon},0a,1000d",
        "OpenStreetMap": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=17/{lat}/{lon}",
        "Yandex Maps": f"https://yandex.com/maps/?pt={lon},{lat}&z=17&l=map",
        "Bing Maps": f"https://www.bing.com/maps?cp={lat}~{lon}&lvl=17",
    }
    date = ""
    if timestamp:
        date = datetime.datetime.fromtimestamp(
            timestamp, tz=datetime.timezone.utc
        ).strftime("%Y.%m.%d")
    links["SunCalc (shadows)"] = f"https://www.suncalc.org/#/{lat},{lon},17/{date}/"
    return links


def reverse_image_links(url: str) -> dict[str, str]:
    encoded = quote(url, safe="")
    return {
        "Google Lens": f"https://lens.google.com/uploadbyurl?url={encoded}",
        "Yandex": f"https://yandex.com/images/search?rpt=imageview&url={encoded}",
        "TinEye": f"https://tineye.com/search?url={encoded}",
        "Baidu": f"https://graph.baidu.com/details?isfromtusoupc=1&tn=pc&image={encoded}",
        "Bing Visual Search": f"https://www.bing.com/images/search?view=detailv2&iss=sbi&form=SBIVSP&sbisrc=UrlPaste&q=imgurl:{encoded}",
    }


OCR_MIN_CHARS = 3
OCR_MAX_CHARS = 600


def dhash(image, hash_size: int = 8) -> str:
    """Difference hash: stays close for visually similar images. Pure PIL."""
    small = image.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = list(small.getdata())
    bits = 0
    for row in range(hash_size):
        for col in range(hash_size):
            left = pixels[row * (hash_size + 1) + col]
            right = pixels[row * (hash_size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


def ocr_text(data: bytes) -> str:
    try:
        import pytesseract
    except ImportError as exc:
        raise ToolError("pytesseract is not installed") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            text = pytesseract.image_to_string(image)
    except pytesseract.TesseractNotFoundError as exc:
        raise ToolError("the tesseract OCR engine is not installed") from exc
    except Exception as exc:
        raise ToolError(f"OCR failed: {type(exc).__name__}") from exc
    cleaned = " ".join(text.split())
    return cleaned


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
    perceptual = ""
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image_format = image.format or "unknown"
            perceptual = dhash(image)
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
                + (f" | dHash: {perceptual}" if perceptual else "")
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

    thumbnail = tags.get("JPEGThumbnail")
    if isinstance(thumbnail, (bytes, bytearray)) and thumbnail:
        results.append(
            {
                "platform": "Embedded thumbnail",
                "status": "found",
                "info": (
                    f"An EXIF thumbnail is embedded ({len(thumbnail)} bytes, "
                    f"SHA-256: {hashlib.sha256(bytes(thumbnail)).hexdigest()}). "
                    "It can differ from the edited full image."
                ),
            }
        )

    try:
        text = ocr_text(data)
        if len(text) >= OCR_MIN_CHARS:
            results.append(
                {
                    "platform": "OCR text",
                    "status": "found",
                    "info": text[:OCR_MAX_CHARS]
                    + ("..." if len(text) > OCR_MAX_CHARS else ""),
                }
            )
        else:
            warnings.append("OCR found no readable text in the image.")
    except ToolError as exc:
        warnings.append(f"OCR skipped: {exc}")

    links: dict[str, str] = {}
    coordinates = gps_coordinates(tags)
    if coordinates:
        lat, lon = coordinates
        capture_ts = gps_datetime_utc(tags)
        approximate_time = capture_ts is None
        if approximate_time:
            capture_ts = approx_datetime_utc(tags, lon)
        geo_parts = [
            f"Decimal: {lat}, {lon}",
            f"DMS: {decimal_to_dms(lat, 'N', 'S')} {decimal_to_dms(lon, 'E', 'W')}",
        ]
        altitude = tags.get("GPS GPSAltitude")
        if altitude:
            geo_parts.append(f"Altitude: {_to_float(altitude.values[0]):.0f} m")
        heading = tags.get("GPS GPSImgDirection")
        if heading:
            bearing = _to_float(heading.values[0])
            geo_parts.append(f"Camera heading: {bearing:.0f}° ({cardinal(bearing)})")
        results.append(
            {
                "platform": "GPS location",
                "url": f"https://www.google.com/maps?q={lat},{lon}",
                "status": "found",
                "info": "; ".join(geo_parts),
            }
        )
        links.update(geo_links(lat, lon, capture_ts))

        if capture_ts is not None:
            azimuth, altitude_deg = sun_position(capture_ts, lat, lon)
            prefix = "Approx (local time assumed): " if approximate_time else ""
            if altitude_deg < -0.833:
                sun_info = (
                    f"{prefix}Sun was below the horizon "
                    f"(altitude {altitude_deg:.0f}°) — night/twilight."
                )
            else:
                shadow_bearing = (azimuth + 180) % 360
                sun_info = (
                    f"{prefix}Sun azimuth {azimuth:.0f}° ({cardinal(azimuth)}), "
                    f"altitude {altitude_deg:.0f}°. Shadows should fall toward "
                    f"{shadow_bearing:.0f}° ({cardinal(shadow_bearing)}). "
                    "Compare with shadows in the image to verify time/place."
                )
            results.append(
                {
                    "platform": "Sun position (shadow check)",
                    "status": "found",
                    "info": sun_info,
                }
            )
    else:
        warnings.append("No GPS coordinates embedded in the image.")

    text_for_geo = ""
    for entry in results:
        if entry.get("platform") == "OCR text":
            text_for_geo = entry.get("info", "")
            break
    if 3 <= len(text_for_geo) <= 60:
        links["Maps search (OCR text)"] = (
            "https://www.google.com/maps/search/"
            + quote(text_for_geo, safe="")
        )

    for name, link in reverse_image_links(url).items():
        results.append(
            {
                "platform": f"Reverse image: {name}",
                "url": link,
                "status": "found",
                "info": "Search for other copies of this image.",
            }
        )

    return {"results": results, "warnings": warnings, "links": links}


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
