import phonenumbers
from phonenumbers import carrier, geocoder, timezone
from phonenumbers.phonenumberutil import (
    NumberParseException,
    PhoneNumberFormat,
    PhoneNumberType,
    format_number,
    number_type,
)

TYPE_LABELS = {
    PhoneNumberType.MOBILE: "mobile",
    PhoneNumberType.FIXED_LINE: "landline",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "mobile/landline",
    PhoneNumberType.VOIP: "VoIP",
    PhoneNumberType.TOLL_FREE: "toll-free",
    PhoneNumberType.PREMIUM_RATE: "premium-rate",
    PhoneNumberType.SHARED_COST: "shared-cost",
    PhoneNumberType.PERSONAL_NUMBER: "personal",
    PhoneNumberType.PAGER: "pager",
    PhoneNumberType.UAN: "UAN",
    PhoneNumberType.VOICEMAIL: "voicemail",
}

DEFAULT_REGION_HINT = "UZ"


class PhoneParseError(ValueError):
    pass


def _parse(raw_number: str):
    try:
        return phonenumbers.parse(raw_number)
    except NumberParseException:
        try:
            return phonenumbers.parse(raw_number, DEFAULT_REGION_HINT)
        except NumberParseException as exc:
            raise PhoneParseError(
                "Could not parse this as a phone number."
            ) from exc


def analyze(raw_number: str) -> dict:
    parsed = _parse(raw_number)
    valid = phonenumbers.is_valid_number(parsed)

    region_desc = geocoder.description_for_number(parsed, "en") or ""
    operator = carrier.name_for_number(parsed, "en") or ""
    line_type = TYPE_LABELS.get(number_type(parsed), "unknown")
    zones = sorted(timezone.time_zones_for_number(parsed))

    info_parts = [
        f"Valid: {'yes' if valid else 'no'}",
        f"Country code: +{parsed.country_code}",
    ]
    if region_desc:
        info_parts.append(f"Region: {region_desc}")
    if operator:
        info_parts.append(f"Carrier: {operator}")
    info_parts.append(f"Line type: {line_type}")
    if zones:
        info_parts.append(f"Timezone: {zones[0]}")

    return {
        "valid": valid,
        "e164": format_number(parsed, PhoneNumberFormat.E164),
        "international": format_number(parsed, PhoneNumberFormat.INTERNATIONAL),
        "national": format_number(parsed, PhoneNumberFormat.NATIONAL),
        "country_code": parsed.country_code,
        "national_number": str(parsed.national_number),
        "region": region_desc,
        "carrier": operator,
        "line_type": line_type,
        "timezone": zones[0] if zones else "",
        "info": " | ".join(info_parts),
    }
