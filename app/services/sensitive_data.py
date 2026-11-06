import re
from typing import Any

_EMAIL = re.compile(r"(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])")
_IBAN_LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22, "BH": 22,
    "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22, "DJ": 27, "DK": 18,
    "DO": 28, "EE": 20, "EG": 29, "ES": 24, "FI": 18, "FO": 18, "FR": 27, "GB": 22, "GE": 22,
    "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HR": 21, "HU": 28, "IE": 22, "IL": 23, "IQ": 23,
    "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LC": 32, "LI": 21, "LT": 20,
    "LU": 20, "LV": 21, "LY": 25, "MA": 28, "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MR": 27,
    "MT": 31, "MU": 30, "NI": 32, "NL": 18, "NO": 15, "OM": 23, "PK": 24, "PL": 28, "PS": 29,
    "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24, "SC": 31, "SD": 18, "SE": 24, "SI": 19,
    "SK": 24, "SM": 27, "SN": 28, "ST": 25, "SV": 28, "TL": 23, "TN": 24, "TR": 26, "UA": 29,
    "VA": 22, "VG": 24, "XK": 20,
}
_IBAN = re.compile(
    r"\b(?:"
    + "|".join(
        rf"{country}\s?\d{{2}}(?:[\s-]?[A-Z0-9]){{{length - 4}}}"
        for country, length in _IBAN_LENGTHS.items()
    )
    + r")\b",
    re.IGNORECASE,
)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_PHONE = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[\s().-]?(?:\d[\s().-]?){7,12}\d|"
    r"00\d{1,3}[\s().-]?(?:\d[\s().-]?){7,12}\d|"
    r"0\d(?:[\s().-]?\d){8,9})(?!\w)"
)
_REDACTIONS = (
    (_IBAN, "[IBAN]", "iban"),
    (_CARD, "[CARD]", "card"),
    (_EMAIL, "[EMAIL]", "email"),
    (_PHONE, "[PHONE]", "phone"),
)


def _valid_iban(value: str) -> bool:
    normalized = re.sub(r"[\s-]", "", value).upper()
    if not 15 <= len(normalized) <= 34 or not normalized[:2].isalpha() or not normalized[2:4].isdigit():
        return False
    rearranged = normalized[4:] + normalized[:4]
    remainder = 0
    for char in rearranged:
        digits = str(ord(char) - ord("A") + 10) if char.isalpha() else char
        for digit in digits:
            remainder = (remainder * 10 + int(digit)) % 97
    return remainder == 1


def _luhn_valid(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def redact_text(value: str) -> str:
    """Masque emails, téléphones, IBAN vérifiés et numéros de carte Luhn valides."""
    text = _IBAN.sub(lambda match: "[IBAN]" if _valid_iban(match.group()) else match.group(), value)
    text = _CARD.sub(lambda match: "[CARD]" if _luhn_valid(match.group()) else match.group(), text)
    text = _EMAIL.sub("[EMAIL]", text)
    return _PHONE.sub("[PHONE]", text)


def redact_value(value: Any) -> Any:
    """Applique le masquage récursivement aux chaînes des messages et réponses structurées."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    return value
