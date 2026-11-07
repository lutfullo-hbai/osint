import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree

OFFICE_CORE_FIELDS = [
    "title",
    "subject",
    "creator",
    "keywords",
    "description",
    "lastModifiedBy",
    "revision",
    "created",
    "modified",
    "category",
    "contentStatus",
]

OFFICE_APP_FIELDS = [
    "Application",
    "AppVersion",
    "Company",
    "Manager",
    "Template",
    "Pages",
    "Words",
    "Characters",
    "TotalTime",
]

PDF_FIELDS = [
    "Author",
    "Creator",
    "Producer",
    "Title",
    "Subject",
    "Keywords",
    "CreationDate",
    "ModDate",
]

EXIFTOOL_FIELDS = [
    "Author",
    "Creator",
    "Producer",
    "Title",
    "Make",
    "Model",
    "Software",
    "Company",
    "LastModifiedBy",
    "CreateDate",
    "ModifyDate",
    "GPSPosition",
]


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_kind(path: str, head: bytes) -> str:
    if head.startswith(b"%PDF"):
        return "PDF"
    if head.startswith(b"PK\x03\x04"):
        extension = os.path.splitext(path)[1].lower()
        if extension in (".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"):
            return "Office / ZIP"
        return "ZIP arxiv"
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG rasm"
    if head.startswith(b"\x89PNG"):
        return "PNG rasm"
    if head.startswith(b"ID3"):
        return "MP3 audio"
    return "Noma'lum / ikkilik"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def office_metadata(path: str) -> dict:
    metadata = {}
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())

        if "docProps/core.xml" in names:
            root = ElementTree.fromstring(archive.read("docProps/core.xml"))
            values = {local_name(child.tag): (child.text or "").strip() for child in root}
            for field in OFFICE_CORE_FIELDS:
                if values.get(field):
                    metadata[field] = values[field]

        if "docProps/app.xml" in names:
            root = ElementTree.fromstring(archive.read("docProps/app.xml"))
            values = {local_name(child.tag): (child.text or "").strip() for child in root}
            for field in OFFICE_APP_FIELDS:
                if values.get(field):
                    metadata[field] = values[field]

        comment_files = [
            name for name in names if re.search(r"(comments|comment)\d*\.xml$", name)
        ]
        if comment_files:
            metadata["commentFiles"] = len(comment_files)

        document = None
        if "word/document.xml" in names:
            document = archive.read("word/document.xml")
        if document:
            tracked = document.count(b"<w:ins ") + document.count(b"<w:del ")
            if tracked:
                metadata["trackedChanges"] = tracked

        comment = archive.comment.decode("utf-8", "ignore").strip()
        if comment:
            metadata["zipComment"] = comment
    return metadata


def pdf_metadata(path: str) -> dict:
    with open(path, "rb") as handle:
        raw = handle.read()
    text = raw.decode("latin-1", "ignore")

    metadata = {}
    for field in PDF_FIELDS:
        match = re.search(rf"/{field}\s*\(([^)]*)\)", text)
        if match and match.group(1).strip():
            metadata[field] = match.group(1).strip()

    if re.search(r"C:\\Users\\|C:\\Documents and Settings", text):
        metadata["windowsPath"] = "PDF ichida Windows yo'li topildi"
    return metadata


def zip_metadata(path: str) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        metadata = {"files": len(names), "preview": names[:15]}
        comment = archive.comment.decode("utf-8", "ignore").strip()
        if comment:
            metadata["zipComment"] = comment
    return metadata


def exiftool_metadata(path: str) -> dict | None:
    if not shutil.which("exiftool"):
        return None
    try:
        result = subprocess.run(
            ["exiftool", "-json", "-G1", "-a", path],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return None
    return data[0] if data else None


def risk_notes(metadata: dict) -> list[str]:
    notes = []
    flat = " ".join(str(value) for value in metadata.values()).lower()

    if any(key in metadata for key in ("creator", "lastModifiedBy", "Author")):
        notes.append("Muallif / tahrirlovchi ismi bor — e'lon qilishdan oldin tozalang.")
    if "Company" in metadata or "Manager" in metadata:
        notes.append("Tashkilot nomi (Company/Manager) bor — ichki ma'lumot.")
    if "windowsPath" in metadata or re.search(r"[a-z]:\\users\\", flat):
        notes.append("Fayl ichida Windows yo'li (username) qolgan.")
    if metadata.get("trackedChanges"):
        notes.append("Office hujjatda kuzatilgan tahrirlar (tracked changes) mavjud.")
    if metadata.get("commentFiles"):
        notes.append("Hujjatda izohlar (comments) fayllari bor.")
    if metadata.get("zipComment"):
        notes.append("Arxiv comment maydonida matn bor — tekshirib ko'ring.")
    if not notes:
        notes.append("Yuqori xavfli metadata maydoni topilmadi (baribir tekshirib ko'ring).")
    return notes


def analyze(path: str) -> dict:
    with open(path, "rb") as handle:
        head = handle.read(16)

    stat = os.stat(path)
    metadata = {}
    kind = detect_kind(path, head)

    if kind == "PDF":
        metadata = pdf_metadata(path)
    elif kind == "Office / ZIP":
        metadata = office_metadata(path)
    elif kind == "ZIP arxiv":
        metadata = zip_metadata(path)

    exiftool = exiftool_metadata(path)
    if exiftool:
        selected = {
            key: value
            for key, value in exiftool.items()
            if key.split(":")[-1] in EXIFTOOL_FIELDS and value not in (None, "")
        }
        if selected:
            metadata["exiftool"] = selected

    return {
        "file": os.path.abspath(path),
        "kind": kind,
        "size": stat.st_size,
        "sha256": sha256(path),
        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "metadata": metadata,
        "notes": risk_notes(metadata),
    }


def main() -> None:
    args = [arg for arg in sys.argv[1:] if arg != "--json"]
    if len(args) != 1:
        print(f"Foydalanish: python3 {sys.argv[0]} <fayl> [--json natija.json]")
        sys.exit(1)

    path = args[0]
    if not os.path.isfile(path):
        print(f"[XATO] Fayl topilmadi: {path}")
        sys.exit(1)

    result = analyze(path)

    print("=" * 56)
    print(f"Fayl: {result['file']}")
    print(f"Tur: {result['kind']} | Hajm: {result['size']} bayt")
    print(f"SHA-256: {result['sha256']}")
    print(f"O'zgartirilgan: {result['modified']}")

    print("\n[Metadata]")
    if not result["metadata"]:
        print("  Metadata topilmadi yoki bu format qo'llab-quvvatlanmaydi.")
    else:
        for key, value in result["metadata"].items():
            if isinstance(value, dict):
                print(f"  {key}:")
                for sub_key, sub_value in value.items():
                    print(f"    {sub_key}: {sub_value}")
            elif isinstance(value, list):
                print(f"  {key}: {', '.join(str(item) for item in value)}")
            else:
                print(f"  {key}: {value}")

    print("\n[Xavf bahosi]")
    for note in result["notes"]:
        print(f"  [!] {note}")

    if "--json" in sys.argv:
        output = sys.argv[sys.argv.index("--json") + 1]
        with open(output, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        print(f"\n[i] Natija saqlandi: {output}")


if __name__ == "__main__":
    main()
