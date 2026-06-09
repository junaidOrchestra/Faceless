# Cookies (optional)

Drop a YouTube **`cookies.txt`** here to fetch videos that fail with *"Sign in
to confirm you're not a bot"* or repeated *HTTP 429*. It is auto-detected — no
env or compose changes needed (just restart the backend).

## How to export cookies.txt

1. Log in to YouTube in your browser.
2. Use a "Get cookies.txt" extension (Netscape format) to export cookies for
   `youtube.com`.
3. Save the file in this folder as `cookies.txt`.
4. `docker compose restart backend` (or `up -d`).

Any `*.txt` in this folder works; `cookies.txt` is preferred if present.

> This folder is gitignored except for this README — your cookies never get
> committed.
