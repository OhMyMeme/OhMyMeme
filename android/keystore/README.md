# Signing keystore (private)

This directory is gitignored except this README. The actual signing key lives in
the **private** repository `OhMyMeme/OhMyMeme-Android-keystore` and is shared by
all developers. Anyone with the key can sign APKs that install over the official
build — do not commit `ohmymeme-release.jks` or `keystore.properties` here.

## Developer setup

1. Clone the private keystore repo to a fixed path (recommended: sibling dir
   `..\OhMyMeme-Android-keystore` next to this checkout).
2. Run the copy script:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/setup-keystore.ps1 -Source ..\OhMyMeme-Android-keystore
   ```

   (auto-detects the sibling directory if `-Source` is omitted.)
3. Build: `.\gradlew :app:assembleRelease` — the APK is signed with the shared key.
   Debug builds use the same key, so any build installs over any other on a device.

Without the key, `assembleDebug` / `assembleRelease` fail at packaging time with a
keystore error — this is intentional so signature stays consistent across the team.

## GitHub Actions

CI does not read these files. It decodes the `SIGNING_KEYSTORE_BASE64` secret and
builds `assembleRelease`. Update the secrets when rotating the key.
