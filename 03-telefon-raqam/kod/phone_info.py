import sys
import phonenumbers
from phonenumbers import carrier, geocoder, timezone


def analyze(raw_number: str) -> None:
    try:
        number = phonenumbers.parse(raw_number)
    except phonenumbers.NumberParseException as error:
        print(f"[XATO] Raqamni o'qib bo'lmadi: {error}")
        return

    print("=" * 40)
    print(f"Raqam: {phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)}")
    print(f"E.164 format: {phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)}")
    print(f"To'g'ri formatda: {phonenumbers.is_valid_number(number)}")
    print(f"Mamlakat: {geocoder.description_for_number(number, 'en')}")

    sim_operator = carrier.name_for_number(number, "en")
    print(f"Operator: {sim_operator if sim_operator else 'Aniqlanmadi'}")

    number_type = phonenumbers.number_type(number)
    types = {
        phonenumbers.PhoneNumberType.MOBILE: "Mobil",
        phonenumbers.PhoneNumberType.FIXED_LINE: "Qutug'i",
        phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "Qutug'i yoki mobil",
        phonenumbers.PhoneNumberType.VOIP: "VoIP (internet telefon)",
        phonenumbers.PhoneNumberType.TOLL_FREE: "Bepul (8-800)",
        phonenumbers.PhoneNumberType.VOICEMAIL: "Ovozli pochta",
    }
    print(f"Turi: {types.get(number_type, 'Boshqa')}")

    try:
        time_zones = timezone.time_zones_for_number(number)
        print(f"Vaqt zonasi: {', '.join(time_zones)}")
    except Exception:
        pass

    telegram_url = f"https://t.me/{phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164).replace('+', '')}"
    print("=" * 40)
    print(f"[i] Telegram tekshiruvi: {telegram_url}")
    print("[i] Google: \"" + phonenumbers.format_number(
        number, phonenumbers.PhoneNumberFormat.E164) + "\"")


def main():
    if len(sys.argv) < 2:
        print(f"Xato: python3 {sys.argv[0]} <+998901234567>")
        sys.exit(1)

    for raw_number in sys.argv[1:]:
        analyze(raw_number)


if __name__ == "__main__":
    main()
