import type { CapacitorConfig } from "@capacitor/cli";

// Brollio Android shell.
//
// The Brollio web app (the Next.js `seemless` app) relies on server-side API
// routes (token-injecting proxies under app/api/*), so it CANNOT be shipped as a
// static bundle. Instead this Capacitor shell loads the HOSTED web app in the
// system WebView via `server.url`. The native project only provides packaging,
// splash, status bar, and (future) native plugin access.
//
// Configure the URL with the CAP_SERVER_URL env var at sync time, e.g.
//   CAP_SERVER_URL=https://app.brollio.com npx cap sync android
// Falls back to the production placeholder below. The `www/` folder is a local
// fallback page Capacitor requires as `webDir`; it is shown only if the remote
// URL can't be reached.
const SERVER_URL = process.env.CAP_SERVER_URL ?? "https://app.brollio.com";

// Allow http ONLY for local-network dev hosts (so `CAP_SERVER_URL=http://10.0.2.2:3000`
// works against a dev machine). Production URLs should always be https.
const isHttp = SERVER_URL.startsWith("http://");

const config: CapacitorConfig = {
  appId: "com.brollio.app",
  appName: "Brollio",
  webDir: "www",
  server: {
    url: SERVER_URL,
    // The WebView must allow navigation to the app's own origin.
    allowNavigation: [new URL(SERVER_URL).host],
    cleartext: isHttp,
    androidScheme: "https",
  },
  android: {
    // Capacitor's WebView already supports the MediaRecorder + canvas.captureStream
    // APIs the animated text-card recorder uses, and the Web Audio SFX synthesis,
    // so the recorder works without extra native plugins on modern Android.
    allowMixedContent: isHttp,
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 800,
      backgroundColor: "#0b0b0d",
      showSpinner: false,
    },
  },
};

export default config;
