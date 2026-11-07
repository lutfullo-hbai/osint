import hashlib
import io
import sys
from urllib.parse import quote

import exifread
import requests
from PIL import Image

MAX_BYTES = 15 * 1024 * 1024
HEADERS = {"User-Agent": "osint-course/1.0 (educational use)"}

INTERESTING_TAGS = [
    "Image Make",
    "Image Model",
    "Image Software",
    "Image DateTime",
    "EXIF DateTimeOriginal",
    "EXIF DateTimeDigitized",
    "EXIF LensModel",
    "EXIF FNumber",
    "EXIF ExposureTime",
    "EXIF ISOSpeedRatings",
    "EXIF FocalLength",
    "EXIF Flash",
]


def load_image(source: str) -> tuple[bytes, str]:
    if source.startswith(("http://", "https://")):
        response = requests.get(source, headers=HEADERS, timeout=20)
        response.raise_for_status()
        data = response.content
        if len(data) > MAX_BYTES:
            raise ValueError("Rasm 15 MB dan katta — yuklash to'xtatildi.")
        return data, source

    with open(source, "rb") as handle:
        data = handle.read()
    if len(data) > MAX_BYTES:
        raise ValueError("Fayl 15 MB dan katta.")
    return data, source


def ratio_to_float(value) -> float:
    try:
        return float(value.num) / float(value.den)
    except (AttributeError, ZeroDivisionError, TypeError):
        return 0.0


def dms_to_decimal(values) -> float:
    degrees = ratio_to_float(values[0])
    minutes = ratio_to_float(values[1])
    seconds = ratio_to_float(values[2])
    return round(degrees + minutes / 60 + seconds / 3600, 6)


def gps_coordinates(tags: dict) -> tuple[float, float] | None:
    latitude = tags.get("GPS GPSLatitude")
    longitude = tags.get("GPS GPSLongitude")
    if not latitude or not longitude:
        return None

    lat = dms_to_decimal(latitude.values)
    lon = dms_to_decimal(longitude.values)
    if str(tags.get("GPS GPSLatitudeRef", "N")).upper().startswith("S"):
        lat = -lat
    if str(tags.get("GPS GPSLongitudeRef", "E")).upper().startswith("W"):
        lon = -lon
    return lat, lon


def reverse_links(url: str) -> dict[str, str]:
    encoded = quote(url, safe="")
    return {
        "Google Lens": f"https://lens.google.com/uploadbyurl?url={encoded}",
        "Yandex": f"https://yandex.com/images/search?rpt=imageview&url={encoded}",
        "TinEye": f"https://tineye.com/search?url={encoded}",
        "Bing Visual Search": (
            "https://www.bing.com/images/search?view=detailv2&iss=sbi"
            f"&form=SBIVSP&sbisrc=UrlPaste&q=imgurl:{encoded}"
        ),
    }


def analyze(source: str) -> None:
    try:
        data, label = load_image(source)
    except (requests.RequestException, OSError, ValueError) as error:
        print(f"[XATO] Rasmni yuklab bo'lmadi: {error}")
        return

    try:
        image = Image.open(io.BytesIO(data))
        width, height = image.size
        image_format = image.format or "noma'lum"
    except Exception as error:
        print(f"[XATO] Rasm formati o'qilmadi: {error}")
        return

    print("=" * 48)
    print(f"Manba: {label}")
    print(f"Format: {image_format} | O'lcham: {width}x{height} | {len(data)} bayt")
    print(f"SHA-256: {hashlib.sha256(data).hexdigest()}")

    tags = exifread.process_file(io.BytesIO(data), details=False)
    print("-" * 48)
    if not tags:
        print("[i] EXIF metadata topilmadi (o'chirilgan yoki olib tashlangan).")
    else:
        for name in INTERESTING_TAGS:
            if name in tags:
                print(f"{name.split(' ', 1)[1]}: {tags[name]}")

        coordinates = gps_coordinates(tags)
        if coordinates:
            lat, lon = coordinates
            print("-" * 48)
            print(f"GPS: {lat}, {lon}")
            print(f"Google Maps: https://www.google.com/maps?q={lat},{lon}")
            print(f"OpenStreetMap: https://www.openstreetmap.org/?mlat={lat}&mlon={lon}")
        else:
            print("[i] GPS koordinatalari yo'q.")

    if label.startswith(("http://", "https://")):
        print("-" * 48)
        print("[i] Teskari qidiruv havolalari:")
        for name, url in reverse_links(label).items():
            print(f"  {name}: {url}")
    else:
        print("-" * 48)
        print("[i] Lokal fayl uchun teskari qidiruvni qo'lda yuklang:")
        print("  https://lens.google.com/  |  https://yandex.com/images/  |  https://tineye.com/")


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Foydalanish: python3 {sys.argv[0]} <rasm_url_yoki_fayl>")
        sys.exit(1)
    analyze(sys.argv[1])


if __name__ == "__main__":
    main()
