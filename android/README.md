# Brollio — Android (Capacitor wrapper)

A thin [Capacitor](https://capacitorjs.com/) shell that packages the Brollio web
app as an installable Android app.

## How it works

The Brollio web app (the `seemless` Next.js app) depends on **server-side API
routes** (the token-injecting proxies under `seemless/app/api/*`), so it cannot
be exported as a static bundle. Instead, this shell loads the **hosted** web app
in the Android System WebView via Capacitor's `server.url`.

- The native project provides packaging, app icon, splash screen, and status bar.
- The WebView runs the real web app, so features keep working as-is — including
  the animated text-card recorder, which uses `MediaRecorder` +
  `canvas.captureStream()` and Web Audio SFX synthesis (all supported by the
  modern Chromium-based Android WebView). No camera/mic permission is needed
  because the recorder captures a canvas + synthesized audio, not the device.
- `www/index.html` is a minimal fallback shown only if the remote URL is
  unreachable.

## Prerequisites

These are **not** installed on the current machine — install them on whatever
machine builds the APK:

- **JDK 17** (Temurin/Adoptium recommended)
- **Android Studio** (bundles the Android SDK, platform-tools, and an emulator)
- Node.js 18+ (already used by the repo)

Set `JAVA_HOME` and `ANDROID_HOME` (e.g. `~/AppData/Local/Android/Sdk` on
Windows) so the Gradle build can find the SDK.

## Configure the target URL

The app loads whatever `server.url` points at. It's read from the
`CAP_SERVER_URL` env var at **sync** time, defaulting to the production
placeholder `https://app.brollio.com` (edit the default in `capacitor.config.ts`
once the real domain is known).

Production:

```bash
CAP_SERVER_URL=https://app.brollio.com npx cap sync android
```

Local dev against `next dev` on your machine (Android emulator reaches the host
via `10.0.2.2`; http enables cleartext automatically):

```bash
# in seemless/:  npm run dev   (serves on :3000)
CAP_SERVER_URL=http://10.0.2.2:3000 npx cap sync android
```

> PowerShell equivalent:
> `$env:CAP_SERVER_URL="http://10.0.2.2:3000"; npx cap sync android`

## Build & run

```bash
npm install                 # once
npx cap sync android        # copy config + web assets, update native project
npx cap open android        # open the project in Android Studio -> Run ▶
```

Or build a debug APK from the CLI (requires JDK + SDK):

```bash
cd android
./gradlew assembleDebug      # gradlew.bat on Windows
# output: android/app/build/outputs/apk/debug/app-debug.apk
```

A release build needs a signing keystore (`./gradlew assembleRelease` after
configuring `signingConfigs` in `android/app/build.gradle`).

## Project layout

```
android/
├─ capacitor.config.ts   # appId, appName, server.url (this is the source of truth)
├─ package.json          # Capacitor deps + helper scripts
├─ www/                  # fallback webDir (offline/unreachable page)
└─ android/              # generated native Android project (open in Android Studio)
```

## Notes / next steps

- **App identity**: `appId` is `com.brollio.app`; change it before publishing if
  needed (also update the Java package + `applicationId` in `android/app/build.gradle`).
- **Icons/splash**: replace the generated placeholder icons (or use
  `@capacitor/assets` to generate them from a source image).
- **Deep links / OAuth**: if Supabase auth uses a redirect, register the custom
  URL scheme (`com.brollio.app`) or an App Link so sign-in returns to the app.
- **iOS**: the same wrapper works for iOS later via `npx cap add ios` (needs a Mac
  + Xcode). Validate `MediaRecorder` on iOS WKWebView specifically — it's the
  riskiest API there.
