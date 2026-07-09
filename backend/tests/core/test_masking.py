import pytest

from app.core.masking import (
    mask_company,
    mask_email,
    mask_emails_in_text,
    mask_phones_in_text,
    mask_pii_in_text,
)


@pytest.mark.parametrize("value", ["", "   ", None])
def test_mask_company_absent_is_none(value: str | None) -> None:
    assert mask_company(value) is None


@pytest.mark.parametrize("value", ["Acme", "Globex Corporation", "a"])
def test_mask_company_present_is_redacted_not_the_name(value: str) -> None:
    masked = mask_company(value)
    assert masked is not None
    assert value not in masked  # the real name never leaks in list views (L5)


def test_masks_standard_email() -> None:
    assert mask_email("ada@acme.com") == "a***@acme.com"


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        "no-at-sign",
        "@acme.com",
        "a@b.co",
        "weird@@double.com",
        "x@y",
        "  spaces @ acme.com",
        "MiXeD@Case.COM",
    ],
)
def test_never_reveals_full_local_part(value: str | None) -> None:
    masked = mask_email(value)
    # The masked form must not contain the original local part (beyond 1 char).
    if value and "@" in value:
        local = value.split("@", 1)[0]
        if len(local) > 1:
            assert local not in masked
        # Domain is preserved; the mask marker is present.
        assert "***" in masked
    # Never raises; always a string.
    assert isinstance(masked, str)


def test_masks_emails_inside_text() -> None:
    text = "Please email ada@acme.com or bob@corp.io for details."
    masked = mask_emails_in_text(text)
    assert "ada@acme.com" not in masked
    assert "bob@corp.io" not in masked
    assert "a***@acme.com" in masked
    assert "b***@corp.io" in masked
    # Surrounding text is untouched.
    assert masked.startswith("Please email ")


@pytest.mark.parametrize(
    "phone",
    ["415-555-0142", "(415) 555-0142", "+1 415 555 0142", "4155550142"],
)
def test_masks_phone_numbers(phone: str) -> None:
    masked = mask_phones_in_text(f"Call me at {phone} anytime")
    assert phone not in masked
    assert "42" in masked  # last two digits retained
    assert masked.startswith("Call me at ")


def test_short_number_is_not_masked_as_phone() -> None:
    # A 4-digit year is not phone-length and must survive untouched.
    assert mask_phones_in_text("in 2024 we grew") == "in 2024 we grew"


def test_mask_pii_masks_both_email_and_phone() -> None:
    text = "Reach ada@acme.com or call 415-555-0142"
    masked = mask_pii_in_text(text)
    assert "ada@acme.com" not in masked
    assert "415-555-0142" not in masked
    assert "a***@acme.com" in masked
