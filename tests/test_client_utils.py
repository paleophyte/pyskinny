import pytest

from utils.client import normalize_mac_address


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("222233334444", "222233334444"),
        ("22:22:33:33:44:44", "222233334444"),
        ("22-22-33-33-44-44", "222233334444"),
        ("2222.3333.4444", "222233334444"),
    ],
)
def test_normalize_mac_address(raw, expected):
    assert normalize_mac_address(raw) == expected


def test_normalize_mac_address_invalid():
    with pytest.raises(ValueError, match="Invalid MAC"):
        normalize_mac_address("abc")
