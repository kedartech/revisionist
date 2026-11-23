# The Android app

The Android app is the installed web app wrapped as a Trusted Web Activity (TWA): Chrome opens the
game's own address full screen, with no address bar. It is the same client at the same address, so
sessions, the origin check and the fog rules are the web's. The app stores no token; the session is
the browser's own cookie.

Nothing here is run by the build or by a lane. Building, signing and uploading need a public HTTPS
address, a signing key and a store account, which only Josh holds.

## Why not the other wrapper

A wrapper that serves the page from inside the app (a WebView shell, or Capacitor with its bundled
page) serves it from another origin. The session cookie is `HttpOnly; SameSite=Strict`
(`guard.cookie`), so a page on another origin never sends it, and every write is checked against the
host the server is served under (`guard.same_origin`), so a write from another origin is refused.
Loosening either would change how a session works. A TWA keeps the page on the game's own address.

## Before you start

- The game is served over HTTPS at a public address, with `--secure-cookie`, and
  `REVISIONIST_PUBLIC_NAMES` lists that name.
- Its page links `manifest.webmanifest` and the worker (`/sw.js`) takes control after one load. Run
  `web/test/e2e/surface_smoke.py` against it first; its checks for the manifest, the worker, the 512 px
  icon and the asset-links address are what the wrapper needs from the web side.

## Steps

1. Install the tool, on your own machine: Node 18 or later and Bubblewrap
   (`npm i -g @bubblewrap/cli`). It needs a JDK and the Android SDK; it offers to download both.
2. Copy `deploy/android/twa-manifest.json` to an empty folder and fill the blanks:
   - `host`: the game's public host name, no scheme;
   - `packageId`: the app's id, for example `app.example.revisionist`;
   - `iconUrl`: `https://<host>/icons/icon-512.png`;
   - `maskableIconUrl`: `https://<host>/icons/icon-maskable-512.png`;
   - `webManifestUrl`: `https://<host>/manifest.webmanifest`.
   The colours match the web manifest; leave them.
3. Make the signing key, once, and keep it and its password off the repository and out of the
   backup directory:
   `keytool -genkeypair -v -keystore revisionist.keystore -alias revisionist -keyalg RSA -keysize 2048 -validity 10000`.
   Put its path in `signingKey.path`.
4. Read the key's SHA-256 fingerprint: `keytool -list -v -keystore revisionist.keystore -alias revisionist`.
   Put it in `fingerprints[0].value`, in the form `AB:CD:...`. If the store signs the app for you
   (Play App Signing), use the fingerprint the Play console shows under App signing instead, or in
   addition.
5. Build: `bubblewrap init --manifest=<the filled twa-manifest.json>` then `bubblewrap build`. It
   writes `app-release-bundle.aab` for the store and `app-release-signed.apk` for a phone.
6. Serve the asset-links file. Write it as the `assetlinks.json` that `bubblewrap fingerprint`
   prints (or by hand):

   ```json
   [{"relation": ["delegate_permission/common.handle_all_urls"],
     "target": {"namespace": "android_app", "package_name": "<packageId>",
                "sha256_cert_fingerprints": ["<the fingerprint>"]}}]
   ```

   Save it outside the repository, set `REVISIONIST_ASSETLINKS_FILE` to its path in the unit's
   environment file and restart the web unit. The server then answers
   `https://<host>/.well-known/assetlinks.json` with it (404 while the setting is unset or the file
   is unreadable). Check the address in a browser, then run the smoke with the same setting in its
   environment: it asserts the address answers with a list naming an Android app.
7. Install the signed APK on a phone (`adb install app-release-signed.apk`) and open it. Check that
   the address bar is gone. If a bar shows, Chrome could not verify the link: the package id or the
   fingerprint in the file does not match the build, or the file is not served at that address.
   Chrome caches a failed check; clear the app's data and reopen after a fix.
8. Upload `app-release-bundle.aab` to the Play console (a new app, internal testing first), and add
   the Play fingerprint to the asset-links file as in step 4 once the console shows it.

## What the web side keeps

The wrapper needs the manifest (name, `start_url` `/`, `display` `standalone`, a 512 px icon and a
maskable one), the worker in control of the page, and the asset-links address. Changing any of them
is a change to this recipe.
