from datetime import date

import pytest

from modules.patients import validators as v


def test_names():
    assert v.normalize_name("  jane ") == "jane"
    assert v.normalize_name("Mary-Ann O'Neil") == "Mary-Ann O'Neil"
    assert v.normalize_name("José") == "José"
    for bad in ("", "John123", "a" * 51, "@@"):
        with pytest.raises(ValueError):
            v.normalize_name(bad, "first name")


def test_date_of_birth_formats_and_rules():
    assert v.parse_date_of_birth("03/14/1987") == date(1987, 3, 14)
    assert v.parse_date_of_birth("1987-03-14") == date(1987, 3, 14)
    assert v.parse_date_of_birth("March 14th, 1987") == date(1987, 3, 14)
    with pytest.raises(ValueError, match="future"):
        v.parse_date_of_birth("03/14/2087")
    with pytest.raises(ValueError, match="valid date"):
        v.parse_date_of_birth("02/30/1990")
    with pytest.raises(ValueError, match="1900"):
        v.parse_date_of_birth("01/01/1850")


def test_sex_aliases():
    assert v.normalize_sex("male") == "Male"
    assert v.normalize_sex("F") == "Female"
    assert v.normalize_sex("prefer not to say") == "Decline to Answer"
    with pytest.raises(ValueError):
        v.normalize_sex("unknown")


def test_phone_normalization():
    assert v.normalize_phone("+1 (212) 555-0188") == "2125550188"
    assert v.normalize_phone("212.555.0188") == "2125550188"
    for bad in ("555", "1234567890", "(012) 555-0188", "212555018"):
        with pytest.raises(ValueError):
            v.normalize_phone(bad)
    assert v.format_phone("2125550188") == "(212) 555-0188"


def test_email_including_spoken_form():
    assert v.normalize_email("Jane.D@Mail.com") == "jane.d@mail.com"
    assert v.normalize_email("jane dot doe at gmail dot com") == "jane.doe@gmail.com"
    assert v.normalize_email("") is None
    with pytest.raises(ValueError):
        v.normalize_email("not-an-email")


def test_state_and_zip():
    assert v.normalize_state("ny") == "NY"
    assert v.normalize_state("New York") == "NY"
    assert v.normalize_state("washington dc") == "DC"
    with pytest.raises(ValueError):
        v.normalize_state("ZZ")
    assert v.normalize_zip("10012") == "10012"
    assert v.normalize_zip("10012-1234") == "10012-1234"
    assert v.normalize_zip("100121234") == "10012-1234"
    for bad in ("1001", "ABCDE", "10012-12"):
        with pytest.raises(ValueError):
            v.normalize_zip(bad)


def test_member_id_and_language():
    assert v.normalize_member_id("w884 2710x") == "W8842710X"
    with pytest.raises(ValueError):
        v.normalize_member_id("bad id!")
    assert v.normalize_language("") == "English"
    assert v.normalize_language("spanish") == "Spanish"


def test_validate_fields_never_raises():
    accepted, errors = v.validate_fields({"first_name": "Jane", "date_of_birth": "13/45/2000", "bogus": 1})
    assert accepted == {"first_name": "Jane"}
    assert "date_of_birth" in errors and "bogus" in errors
