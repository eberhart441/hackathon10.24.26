<#
.SYNOPSIS
  Flash a prebuilt Beacon node image. No ESP-IDF needed.

.DESCRIPTION
  Uses the esptool that the Arduino IDE already installed for the ESP32 boards
  (or any esptool on PATH). The Arduino IDE itself cannot upload this firmware,
  because it is an ESP-IDF program, not an Arduino sketch; esptool can.

.PARAMETER Port
  Serial port of the board, for example COM5.

.PARAMETER Chip
  esp32 (classic boards such as "ESP32 Dev Module", the only chip with a prebuilt image).
  If unsure, run:  esptool --port COM5 chip-id   (it prints the chip type).

.PARAMETER Baud
  Flash speed. Lower it (115200) if flashing fails with a "timed out" error.

.PARAMETER Erase
  Erase the whole flash first. This also wipes the saved node settings.

.EXAMPLE
  .\flash.ps1 -Port COM5
#>
param(
    [Parameter(Mandatory = $true)][string]$Port,
    [ValidateSet('esp32')][string]$Chip = 'esp32',
    [int]$Baud = 460800,
    [string]$Image,
    [switch]$Erase
)

$ErrorActionPreference = 'Stop'
if (-not $Image) {
    $Image = Join-Path $PSScriptRoot "prebuilt\beacon-$Chip.bin"
}
if (-not (Test-Path $Image)) {
    throw "Image not found: $Image"
}

# Find an esptool: newest one installed by the Arduino IDE, else one on PATH.
$esptool = $null
$major = 5
$arduinoTools = Join-Path $env:LOCALAPPDATA 'Arduino15\packages\esp32\tools\esptool_py'
if (Test-Path $arduinoTools) {
    $best = Get-ChildItem $arduinoTools -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName 'esptool.exe') } |
        Sort-Object { [version]($_.Name -replace '[^0-9.]', '') } -Descending |
        Select-Object -First 1
    if ($best) {
        $esptool = Join-Path $best.FullName 'esptool.exe'
        $major = [int]($best.Name.Split('.')[0])
    }
}
if (-not $esptool) {
    $cmd = Get-Command esptool, esptool.py -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cmd) {
        throw 'No esptool found. Install the ESP32 board package in the Arduino IDE, or run: pip install esptool'
    }
    $esptool = $cmd.Source
}

# esptool 5 uses hyphenated commands; 4.x uses underscores.
$writeCmd = if ($major -ge 5) { 'write-flash' } else { 'write_flash' }
$eraseCmd = if ($major -ge 5) { 'erase-flash' } else { 'erase_flash' }

Write-Host "Using $esptool"
if ($Erase) {
    & $esptool --chip $Chip --port $Port --baud $Baud $eraseCmd
    if ($LASTEXITCODE -ne 0) { throw 'Erase failed.' }
}
& $esptool --chip $Chip --port $Port --baud $Baud $writeCmd 0x0 $Image
if ($LASTEXITCODE -ne 0) {
    throw 'Flashing failed. Check the port and chip type; for some boards hold the BOOT button while it connects.'
}

Write-Host ''
Write-Host 'Done. Next, open the port at 921600 baud (line ending: Newline) and configure the node:'
Write-Host '  CFG SET node_id RX1'
Write-Host '  CFG SET role rx'
Write-Host '  REBOOT'
