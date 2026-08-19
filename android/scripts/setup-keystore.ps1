# Copies the shared signing keystore from the private keystore repo into this checkout.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/setup-keystore.ps1 [-Source <private-keystore-dir>]
#   -Source defaults to a sibling directory ..\OhMyMeme-Android-keystore

param(
    [string]$Source = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$targetDir = Join-Path $projectRoot "keystore"
$targetKey = Join-Path $targetDir "ohmymeme-release.jks"
$targetProps = Join-Path $projectRoot "keystore.properties"

if (-not $Source) {
    $Source = Join-Path (Split-Path -Parent $projectRoot) "OhMyMeme-Android-keystore"
}

$srcKey = Join-Path $Source "ohmymeme-release.jks"
$srcProps = Join-Path $Source "keystore.properties"

if (-not (Test-Path $srcKey)) { throw "Keystore not found: $srcKey" }
if (-not (Test-Path $srcProps)) { throw "Properties not found: $srcProps" }

New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
Copy-Item $srcKey $targetKey -Force
Copy-Item $srcProps $targetProps -Force

Write-Host "Keystore copied:"
Write-Host "  $targetKey"
Write-Host "  $targetProps"
Write-Host "Both files are gitignored. Build with: .\gradlew :app:assembleRelease"
