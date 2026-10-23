import re

_BUSINESS_ID = re.compile(r"^(\d{7})-(\d)$")
_WEIGHTS = (7, 9, 10, 5, 8, 4, 2)


def is_valid_business_id(value: str) -> bool:
    """Validate a Finnish business ID (Y-tunnus), e.g. ``0112038-9``."""
    match = _BUSINESS_ID.match(value)
    if not match:
        return False
    digits, check = match.groups()
    remainder = sum(int(d) * w for d, w in zip(digits, _WEIGHTS)) % 11
    if remainder == 1:
        return False
    expected = 0 if remainder == 0 else 11 - remainder
    return int(check) == expected
