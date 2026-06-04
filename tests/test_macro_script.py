"""Macro script parser and shared runtime tests."""

from pathlib import Path

from utils.macro_script import parse_macro_script, parse_switch_cases
from utils.macro_runtime import play_prompt_with_barge_in, wav_duration_sec


def test_parse_macro_skips_comments_and_labels():
    script = """
# comment
TOP:
WAIT 1
GOTO MENU
MENU:
END
"""
    instructions, labels = parse_macro_script(script)
    assert labels["TOP"] == 0
    assert labels["MENU"] == 2
    assert instructions[0].command == "WAIT"
    assert instructions[2].command == "END"


def test_parse_switch_cases():
    labels = {"A": 10, "B": 20, "FALLBACK": 30}
    cases, default = parse_switch_cases("1:A;2:B;DEFAULT:FALLBACK", labels)
    assert cases["1"] == 10
    assert cases["2"] == 20
    assert default == 30


def test_ivr_barge_in_stops_playback():
    from simulator.ivr_macro_runner import SimIvrMacroRunner

    class _Media:
        def __init__(self):
            self.stop_count = 0

        def stop_playback(self, call_ref: int) -> bool:
            self.stop_count += 1
            return True

        def play_wav(self, call_ref, path, **kwargs):
            return True

        def set_loopback(self, call_ref):
            return True

        def set_tone(self, call_ref):
            return True

    class _Caller:
        def send(self, _packet):
            pass

    class _Call:
        call_ref = 1
        line = 1
        caller = _Caller()

    class _Hub:
        media_hub = None

        def end_call(self, **kwargs):
            pass

    media = _Media()
    runner = SimIvrMacroRunner(
        _Call(),
        _Hub(),
        media,
        assets_dir=Path("."),
        script_text="PLAY x.wav\n",
    )
    runner.submit_digit("1")
    assert media.stop_count == 1
    assert runner._digit_queue[0] == "1"


def test_play_prompt_with_barge_in(tmp_path):
    wav = tmp_path / "beep.wav"
    import struct

    # minimal 16-bit mono 8kHz 100ms silence
    nframes = 800
    pcm = struct.pack(f"<{nframes}h", *([0] * nframes))
    import wave as wave_mod

    with wave_mod.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(pcm)

    stopped = []
    digits = iter(["1", None, None])

    barged = play_prompt_with_barge_in(
        path=wav,
        start=lambda p: None,
        stop=lambda: stopped.append(True),
        poll_digit=lambda: next(digits),
        log_ctx="test",
    )
    assert barged is True
    assert stopped
