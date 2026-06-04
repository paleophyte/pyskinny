# IVR prompt assets

Drop 16-bit PCM WAV files here for the keypad-driven virtual IVR (`--ivr-dn`).

| File | When played |
|------|-------------|
| `welcome.wav` | Once when the caller connects (before menu) |

Generate on Windows (built-in SAPI):

```powershell
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SetOutputToWaveFile("welcome.wav")
$s.Speak("Welcome to the test IVR. Press 1 for loopback, 2 for tone, 9 to hang up.")
$s.Dispose()
```

Menu keys (Skinny keypad during connected call):

- **1** — loopback echo
- **2** — test tone
- **9** or **#** — hang up

Optional future prompts: `menu.wav`, `goodbye.wav`, etc.
