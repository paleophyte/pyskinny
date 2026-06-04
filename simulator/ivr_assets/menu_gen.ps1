# Generate IVR prompt WAVs into simulator/ivr_assets (Windows SAPI, no extra deps).
param(
    [string]$OutDir = (Join-Path $PSScriptRoot "..\simulator\ivr_assets")
)

$OutDir = (Resolve-Path $OutDir).Path
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$path = Join-Path $OutDir "welcome.wav"
$synth.SetOutputToWaveFile($path)
$synth.Speak("Welcome to the test IVR. Press 1 for loopback, 2 for tone, 9 to hang up.")
$synth.Dispose()
Write-Host "Wrote $path"
