import struct
import time
import warnings
from types import SimpleNamespace

from messages.capabilities import parse_time_date
from state import PhoneState


def test_parse_time_date_uses_utc_fromtimestamp():
    state = PhoneState(server="10.0.0.1", mac="222233334444", model="7970")
    state.device_name = "SEP222233334444"
    client = SimpleNamespace(state=state)
    w_systemtime = 1_700_000_000
    payload = struct.pack(
        "<IIIIIIIII",
        2023,
        11,
        4,
        15,
        10,
        13,
        20,
        0,
        w_systemtime,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        parse_time_date(client, payload)
    assert state.w_system_time == w_systemtime
    assert "UTC" in state.w_system_time_desc
    assert state.initial_time_dt.year == 2023
