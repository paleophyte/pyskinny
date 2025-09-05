import os
from pydub.generators import Sine
from pydub import AudioSegment

# Define tone specifications
tones = {
    "inside_dial_tone": {"freqs": [350, 440], "duration": 30 * 1000, "pattern": "continuous"},
    "outside_dial_tone": {"freqs": [420], "duration": 30 * 1000, "pattern": "continuous"},
    "busy_tone": {"freqs": [480, 620], "on": 500, "off": 500, "duration": 5 * 1000, "pattern": "intermittent"},
    "reorder_tone": {"freqs": [480, 620], "on": 250, "off": 250, "duration": 5 * 1000, "pattern": "intermittent"},
    "alerting_tone": {"freqs": [440], "on": 1000, "off": 4000, "duration": 31 * 1000, "pattern": "intermittent"},
    "call_waiting_tone": {"freqs": [440], "on": 300, "off": 9700, "duration": 30 * 1000, "pattern": "intermittent"},
    "phone_ring": {"freqs": [440], "on": 2000, "off": 4000, "duration": 30 * 1000, "pattern": "intermittent"},
    # Key press feedback tone (short single beep)
    "key_beep": {"freqs": [1000], "duration": 100, "pattern": "continuous"},
}

current_directory = os.getcwd()
output_dir = os.path.join(current_directory, "cisco_tones")
os.makedirs(output_dir, exist_ok=True)

def generate_continuous_tone(freqs, duration_ms):
    combined = sum(Sine(freq).to_audio_segment(duration=duration_ms) for freq in freqs)
    return combined - 3  # reduce volume slightly

def generate_intermittent_tone(freqs, on_ms, off_ms, duration_ms):
    one_cycle = sum(Sine(freq).to_audio_segment(duration=on_ms) for freq in freqs)
    silence = AudioSegment.silent(duration=off_ms)
    full_segment = AudioSegment.empty()
    total = 0
    while total < duration_ms:
        full_segment += one_cycle + silence
        total += on_ms + off_ms
    return full_segment - 3

# Generate and export each tone
for name, spec in tones.items():
    if spec["pattern"] == "continuous":
        audio = generate_continuous_tone(spec["freqs"], spec["duration"])
    else:
        audio = generate_intermittent_tone(spec["freqs"], spec["on"], spec["off"], spec["duration"])
    audio.export(os.path.join(output_dir, f"{name}.wav"), format="wav")

print("✅ All tones (including key_beep) generated in ./cisco_tones/")
