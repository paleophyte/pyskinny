# IVR prompt assets

Scripts and WAV prompts for the virtual IVR (`--ivr-dn 9999`).

## Macro script

Edit `ivr.macro` — same format as `examples/ivr.macro`, plus sim-only commands:

| Command | Meaning |
|---------|---------|
| `PLAY welcome.wav` | Stream WAV to caller over RTP |
| `WAIT_DIGIT 0` | Wait for Skinny keypad (0 = forever) |
| `SWITCH last_digit 1:LOOPBACK;...` | Branch on last digit |
| `LOOPBACK` | Echo caller mic back (needs client mic + monitor; now default) |
| `TONE` | Play test tone |
| `PROMPT text` | Update phone display prompt |
| `END` | Hang up |

Generate prompts with `menu_gen.ps1` in this folder.

## Minimal lab commands

```powershell
python -m examples.run_simulator -vv --advertise-host 10.102.172.11 --tftp-port 6969 --ivr-dn 9999
python -m examples.run_console -vvvv --server 10.102.172.11 --mac 222233334444 --model 7970
```

No extra RTP flags needed — console defaults to mic + local monitor when audio is on.
