"""
Field-level validation + normalization for the patient demographic data model.

This module is the single source of truth for the rules in the assessment spec. It is used by:
  * the REST API (pydantic schemas call these in `field_validator`s), and
  * the voice agent tools (so the agent can re-prompt for exactly the field that failed).

Every function takes the raw value, returns the canonical stored form, and raises `ValueError`
with a short, human-friendly message that can be read back to a caller.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from email_validator import EmailNotValidError, validate_email

SEX_VALUES = ("Male", "Female", "Other", "Decline to Answer")

# Spoken / alternate phrasings the voice agent or API clients may send.
_SEX_ALIASES = {
    "m": "Male",
    "male": "Male",
    "man": "Male",
    "f": "Female",
    "female": "Female",
    "woman": "Female",
    "other": "Other",
    "non-binary": "Other",
    "nonbinary": "Other",
    "decline": "Decline to Answer",
    "decline to answer": "Decline to Answer",
    "prefer not to say": "Decline to Answer",
    "prefer not to answer": "Decline to Answer",
    "rather not say": "Decline to Answer",
    "skip": "Decline to Answer",
}

US_STATES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
    # Territories - accepted because USPS addresses in them are valid U.S. addresses.
    "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands", "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}
_STATE_BY_NAME = {name.lower(): abbr for abbr, name in US_STATES.items()}
_STATE_BY_NAME["washington dc"] = "DC"
_STATE_BY_NAME["washington d.c."] = "DC"

_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
_MEMBER_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,50}$")


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


# --------------------------------------------------------------------------- names
def normalize_name(value: object, field_label: str = "name") -> str:
    """1-50 chars; letters (any script) plus hyphens/apostrophes; internal spaces allowed (e.g. 'Mary Ann').

    Spaces are a deliberate, documented relaxation of the spec so multi-word names are not rejected.
    """
    text = re.sub(r"\s+", " ", _clean(value)).replace("’", "'")
    if not text:
        raise ValueError(f"{field_label} is required")
    if len(text) > 50:
        raise ValueError(f"{field_label} must be 50 characters or fewer")
    for ch in text:
        if not (ch.isalpha() or ch in "-' "):
            raise ValueError(f"{field_label} may only contain letters, hyphens and apostrophes")
    if not any(ch.isalpha() for ch in text):
        raise ValueError(f"{field_label} must contain letters")
    return text


def normalize_full_name(value: object, field_label: str = "name") -> str:
    """Looser rule for emergency contact 'full name' (letters, spaces, hyphens, apostrophes, periods)."""
    text = re.sub(r"\s+", " ", _clean(value)).replace("’", "'")
    if not text:
        raise ValueError(f"{field_label} is required")
    if len(text) > 100:
        raise ValueError(f"{field_label} must be 100 characters or fewer")
    for ch in text:
        if not (ch.isalpha() or ch in "-'. "):
            raise ValueError(f"{field_label} may only contain letters, spaces, hyphens and apostrophes")
    return text


# ------------------------------------------------------------------ date of birth
_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%m/%d/%y")


def parse_date_of_birth(value: object, today: date | None = None) -> date:
    """Accepts MM/DD/YYYY (spec), ISO YYYY-MM-DD, or a date object. Must be a real date, not in the future, >= 1900."""
    today = today or date.today()
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        parsed = value
    else:
        text = _clean(value).replace(",", ", ").replace("  ", " ")
        text = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", text)  # "March 14th 1987" -> "March 14 1987"
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            raise ValueError("date of birth is required")
        parsed = None
        for fmt in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError("date of birth must be a valid date in MM/DD/YYYY format")
    if parsed > today:
        raise ValueError("date of birth cannot be in the future")
    if parsed.year < 1900:
        raise ValueError("date of birth must be after 1900")
    return parsed


def format_date_mmddyyyy(value: date) -> str:
    return value.strftime("%m/%d/%Y")


# --------------------------------------------------------------------------- sex
def normalize_sex(value: object) -> str:
    text = _clean(value)
    if not text:
        raise ValueError("sex is required")
    key = text.lower()
    if key in _SEX_ALIASES:
        return _SEX_ALIASES[key]
    for canonical in SEX_VALUES:
        if key == canonical.lower():
            return canonical
    raise ValueError("sex must be one of: Male, Female, Other, Decline to Answer")


# ------------------------------------------------------------------------- phone
def normalize_phone(value: object, field_label: str = "phone number") -> str:
    """Returns exactly 10 digits. Accepts +1 / 1 prefix, spaces, dashes, dots, parentheses."""
    text = _clean(value)
    if not text:
        raise ValueError(f"{field_label} is required")
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError(f"{field_label} must be a 10-digit U.S. number")
    if digits[0] in "01" or digits[3] in "01":
        raise ValueError(f"{field_label} is not a valid U.S. number (area code or exchange cannot start with 0 or 1)")
    return digits


def format_phone(digits: str | None) -> str | None:
    if not digits or len(digits) != 10:
        return digits
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


# ------------------------------------------------------------------------- email
def normalize_email(value: object) -> str | None:
    text = _clean(value)
    if not text:
        return None
    # Voice transcripts often come as "jane dot doe at gmail dot com"
    spoken = re.sub(r"\s+at\s+", "@", text, flags=re.IGNORECASE)
    spoken = re.sub(r"\s+dot\s+", ".", spoken, flags=re.IGNORECASE)
    spoken = spoken.replace(" ", "")
    try:
        result = validate_email(spoken, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError(f"email is not valid: {exc}") from exc
    if len(result.normalized) > 254:
        raise ValueError("email must be 254 characters or fewer")
    return result.normalized.lower()


# ----------------------------------------------------------------------- address
def normalize_text(value: object, field_label: str, max_length: int, required: bool = True) -> str | None:
    text = re.sub(r"\s+", " ", _clean(value))
    if not text:
        if required:
            raise ValueError(f"{field_label} is required")
        return None
    if len(text) > max_length:
        raise ValueError(f"{field_label} must be {max_length} characters or fewer")
    return text


def normalize_state(value: object) -> str:
    text = _clean(value)
    if not text:
        raise ValueError("state is required")
    upper = text.upper().replace(".", "")
    if upper in US_STATES:
        return upper
    abbr = _STATE_BY_NAME.get(text.lower().replace(".", ""))
    if abbr:
        return abbr
    raise ValueError("state must be a valid 2-letter U.S. state abbreviation")


def normalize_zip(value: object) -> str:
    text = _clean(value).replace(" ", "")
    if not text:
        raise ValueError("zip code is required")
    if len(text) == 9 and text.isdigit():
        text = f"{text[:5]}-{text[5:]}"
    if not _ZIP_RE.match(text):
        raise ValueError("zip code must be 5 digits or ZIP+4 (e.g. 10012 or 10012-1234)")
    return text


# --------------------------------------------------------------------- insurance
def normalize_member_id(value: object) -> str | None:
    text = _clean(value).replace(" ", "").upper()
    if not text:
        return None
    if not _MEMBER_ID_RE.match(text):
        raise ValueError("insurance member id must be alphanumeric (hyphens allowed), up to 50 characters")
    return text


def normalize_language(value: object) -> str:
    text = re.sub(r"\s+", " ", _clean(value))
    if not text:
        return "English"
    if len(text) > 50:
        raise ValueError("preferred language must be 50 characters or fewer")
    return text[:1].upper() + text[1:]


# ------------------------------------------------------------------- convenience
REQUIRED_FIELDS = (
    "first_name",
    "last_name",
    "date_of_birth",
    "sex",
    "phone_number",
    "address_line_1",
    "city",
    "state",
    "zip_code",
)
OPTIONAL_FIELDS = (
    "email",
    "address_line_2",
    "insurance_provider",
    "insurance_member_id",
    "preferred_language",
    "emergency_contact_name",
    "emergency_contact_phone",
)
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


def normalize_field(name: str, value: object):
    """Dispatch a single field to its normalizer. Returns the canonical value (None for empty optionals)."""
    if name == "first_name":
        return normalize_name(value, "first name")
    if name == "last_name":
        return normalize_name(value, "last name")
    if name == "date_of_birth":
        return parse_date_of_birth(value)
    if name == "sex":
        return normalize_sex(value)
    if name == "phone_number":
        return normalize_phone(value)
    if name == "email":
        return normalize_email(value)
    if name == "address_line_1":
        return normalize_text(value, "street address", 200)
    if name == "address_line_2":
        return normalize_text(value, "apartment/suite", 100, required=False)
    if name == "city":
        return normalize_text(value, "city", 100)
    if name == "state":
        return normalize_state(value)
    if name == "zip_code":
        return normalize_zip(value)
    if name == "insurance_provider":
        return normalize_text(value, "insurance provider", 100, required=False)
    if name == "insurance_member_id":
        return normalize_member_id(value)
    if name == "preferred_language":
        return normalize_language(value)
    if name == "emergency_contact_name":
        text = _clean(value)
        return normalize_full_name(text, "emergency contact name") if text else None
    if name == "emergency_contact_phone":
        text = _clean(value)
        return normalize_phone(text, "emergency contact phone") if text else None
    raise ValueError(f"unknown field '{name}'")


def validate_fields(values: dict) -> tuple[dict, dict[str, str]]:
    """Normalize many fields at once. Returns (accepted, errors) - never raises."""
    accepted: dict = {}
    errors: dict[str, str] = {}
    for name, raw in values.items():
        if name not in ALL_FIELDS:
            errors[name] = f"unknown field '{name}'"
            continue
        try:
            accepted[name] = normalize_field(name, raw)
        except ValueError as exc:
            errors[name] = str(exc)
    return accepted, errors
