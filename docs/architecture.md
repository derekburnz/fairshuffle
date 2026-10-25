# FairShuffle architecture

How the app is put together: its parts, the threads they run on, the sign-in and shuffle flows and where data lives. This started as section 3 of [`planning/ROADMAP.md`](planning/ROADMAP.md) (approved 2026-10-09) and is kept in step with the code from milestone M1 on.

## What exists today

M1 (v0.1.0) built the app's frame, M2 (v0.2.0) added signing in to Spotify and M3 (v0.3.0) added the playlist picker. M4 (v0.4.0) added the shuffle itself under `shuffle/` and the backups, checked against the real Spotify with `scripts/live_shuffle_test.py`; the picker's Shuffle and Undo buttons are wired to it in M5. Everything else in this document is the plan for the milestones after it.

| Module | What it does now |
|--------|------------------|
| `__main__.py` | Parses `--version`, then starts the app |
| `app.py` | Starts logging, builds the `QApplication`, runs the single-instance guard and shows the tray icon. The first copy holds a lock file in the user's temp folder and listens on a per-user local socket (a named pipe on Windows); a later launch connects, hangs up and exits, and the first copy shows a tray message. The guard fails open: if the lock can't be used, the app still starts |
| `config.py` | Reads `SPOTIFY_CLIENT_ID` and `SPOTIFY_REDIRECT_URI`: the environment first, then the gitignored `.env` in a source checkout (python-dotenv, P2-3). An empty or placeholder Client ID, or a Redirect URI that isn't `http://127.0.0.1` with a port, stops with a message pointing at `docs/spotify-setup.md`. Masks the Client ID as soon as it is read; tests point it at a `.env` that doesn't exist (M2) |
| `ui/tray.py` | Tray icon with a placeholder image, tooltip and menu. The menu starts with a greyed-out account line ("Signed in as ...", "Not signed in to Spotify", "Your Spotify sign-in has expired") and one account action (Sign in, Cancel sign-in, Sign out, Sign in again or Try again), then About and Quit. Account messages appear once as tray notifications. While signed in the menu also has "Shuffle a playlist...", and a left-click on the icon opens the picker instead of the menu (D11 B, M3) |
| `ui/picker.py` | The playlist picker window (D11 B, about 380 x 520, `docs/screenshots/picker-window.png`): account line, search box (plain text, any case), the playlists with item counts, a summary or status line, Refresh and a Shuffle button that stays disabled until M4. Rows have a fixed height, names too long for the row end in an ellipsis with the full name in the tooltip, and each row gives screen readers its name and count. Names are only ever shown as plain text: the labels are set to plain text and the tooltip is our own HTML with the name escaped, since a collaborator can name a playlist `<img src=...>`. When there is nothing to list, the list's space says why (`docs/screenshots/picker-states.png`): no playlists you can edit yet (with what to do), a first load that failed (press Refresh), or a search with no match. A failed Refresh keeps the last list and says it is from before. Thousands of playlists fill the list in one model update, and while a search narrows it the status line reads "Showing 12 of 1,204 playlists". Down from the search box moves into the list and Esc hides the window; closing only hides it, so search and selection are kept (M3) |
| `ui/playlists.py` | Loads the playlists behind the picker on Qt's thread pool, like `ui/account.py`: asks `GET /me` for the user ID once per sign-in, then lists the editable playlists. While a refresh runs, or after one fails, the last list stays on show. Signing out drops the list, and a generation number drops any result that arrives after a sign-out or a newer refresh. Errors show FairShuffle's own messages; a bug of ours shows a fixed sentence and is logged by class name only (M3) |
| `ui/account.py` | The account behind the menu. At start it resumes a saved sign-in without the browser. Sign in, sign out and the `/me` lookup run on Qt's thread pool and report back through a signal, so the tray never freezes. A result that arrives after the user moved on is dropped. The display name is shown, never logged (M2). Sign out first ends the old sign-in (`SpotifyAuth.end()`), waiting for any refresh another worker is in the middle of, so a playlist load still running can't save a new token after the delete and sign the account back in at the next start (M3) |
| `ui/about.py` | About box with version, license and source link |
| `auth/pkce.py` | Makes the one-time values for a PKCE sign-in (RFC 7636): a 43-character `code_verifier` and a `state` from the `secrets` module, and the S256 `code_challenge`. `state` is compared in constant time. Pure functions, no I/O (M2) |
| `auth/loopback.py` | One-shot web listener for Spotify's sign-in callback. Reads and checks the Redirect URI (`http://127.0.0.1` with a port, never `localhost`), binds to 127.0.0.1 only (exclusively on Windows), answers on that path only, checks `state` before anything else, returns the code and stops after the first callback or a timeout (five minutes by default). It serves no files and never logs a request line, because the query holds the code (M2) |
| `auth/oauth.py` | Spotify's token endpoint over requests (D9): builds the authorize URL with the four playlist scopes plus `user-read-private` for the profile name (P2-4), swaps the code plus `code_verifier` for tokens, refreshes and keeps the old refresh token when Spotify sends no new one. `SpotifyAuth` holds one run's sign-in, shared by worker threads under a lock: it refreshes a minute before the access token runs out, and on a 401 refreshes once and sends the call again. It sends the token only to `https://api.spotify.com`, refuses a session with certificate checks off, and once Spotify ends the sign-in no other thread asks again. `400 invalid_grant` is never retried: the saved token is removed and `SignInRequired` is raised. No client secret, no redirects on token calls, every code and token masked, errors quote only Spotify's short error code (M2) |
| `auth/sign_in.py` | One browser sign-in: makes the PKCE values, binds the listener before opening the browser, waits for the callback and swaps the code for tokens. `cancel()` works from any thread (M2) |
| `auth/token_store.py` | Saves, loads and deletes the Spotify refresh token in Windows Credential Manager through keyring (D10), under service `FairShuffle`, account `spotify-refresh-token`. Registers every token it sees with `mask_secret()`; its errors never quote a token or carry the store's own exception. Credential Manager is per Windows user, not per app, so any program running as that user could read the entry; that is the accepted limit of D10. Tests get an in-memory store, and outside it keyring's fail backend, so no test or child process can reach the real one (M2) |
| `spotify/client.py` | Sends every Web API call through `SpotifyAuth`. Waits and retries on 429 (`Retry-After`, or backoff when it is missing) but hands `QUOTA_EXCEEDED` and waits over a minute back as `RateLimited`. Backs off on 5xx and dropped connections for reads only: a change such as a reorder is retried only when it surely never took effect (a 429, or a connection that never opened), and otherwise `SpotifyUnavailable(may_have_applied=True)` tells the caller to re-read the playlist first. Maps 403 to `NotOwner` for playlists and `AccessDenied` elsewhere. Follows only `https://api.spotify.com/v1/` links, never follows a redirect, shows `{id}` in place of any ID in a log line, refuses paths with `..`, a backslash, an encoded dot, slash or backslash (`%2e`, `%2f`, `%5c`) or control characters and never logs a query string or body (M2) |
| `spotify/ratelimit.py` | Reads `Retry-After` and the `QUOTA_EXCEEDED` body, and gives the exponential backoff with full jitter (a random wait up to 1, 2, 4... seconds, capped at 30) used when Spotify gives no wait (M2) |
| `spotify/profile.py` | Reads `display_name` from `GET /me` for the menu, with control and direction characters removed and long names cut (M2), and the user's `id`, which playlists name as their owner (M3) |
| `spotify/playlists.py` | Lists the playlists FairShuffle can reorder: `GET /me/playlists` in pages of 50. Spotify's `next` link only says another page exists: FairShuffle asks for the same path at the next offset itself, so a reply can't choose what is fetched or logged. A page without an items list, one that holds more than 50 or is short but claims a next page, or more than 2,000 pages, is refused rather than handing back part of the list. Keeps playlists the user owns or that are collaborative, skips malformed entries, IDs that aren't plain base62 and `snapshot_id`s that aren't up to 256 printable ASCII characters, cuts names past 500 characters, reads the count from `items.total` (never the deprecated `tracks.total`) and logs only how many it found, never a name. Reads a playlist's items from `GET /playlists/{id}/items` the same way, with `additional_types=track,episode`: songs, episodes, local files and items that are no longer available all keep their position, because reorders move items by position. Reads `item`, never the deprecated `track`; a URI that isn't a printable `spotify:` URI of at most 1,000 characters counts as unavailable (M3) |
| `spotify/cache.py` | Keeps each playlist's items in memory with the `snapshot_id` they were read at. While `GET /me/playlists` still reports that `snapshot_id`, the items are handed back without a single item call. Holds at most 50 playlists and 50,000 items in all (least recently used goes first, and a bigger playlist is not kept), belongs to one sign-in (a different client drops everything), stops a read under way from storing after `clear()` or `forget()`, is safe to share between worker threads and never writes to disk. Callers pass a `Playlist` from a fresh read, never a `snapshot_id` they saw before reading the items. Nothing reads items in M3, so the M4 shuffle wires it in and calls `clear()` at sign-out and `forget()` after each shuffle (M3) |
| `spotify/models.py` | Plain dataclasses the rest of the app uses instead of Spotify's JSON: `Playlist` (id, name, owner, collaborative, `snapshot_id`, item count or None) and `PlaylistItem` (position, URI or None, track or episode, local file flag) (M3) |
| `shuffle/engine.py` | Fisher-Yates: walks the list from the end and swaps each position with one from 0 up to itself, so all n! orders are equally likely, with `secrets.SystemRandom` as the random source. A chi-square test over 24,000 shuffles checks every order of four comes up equally often, and proves the common "swap with any position" mistake fails it (M4) |
| `shuffle/planner.py` | Turns the shuffled order into writes before any call (D12). Fast: replace with the first 100 URIs, then add 100 at a time; local files and items with no URI can't be written, so they are counted for the "ask first" dialog (P4-2), and an order with nothing writable is refused. Keep-order: one reorder move per position from the top, at most n - 1, none for an entry already in place, entries named by position so duplicates move correctly (M4) |
| `shuffle/runner.py` | Runs a shuffle or an Undo on a worker thread without Qt: reads the `snapshot_id`, the items (through the cache) and the `snapshot_id` again, stops if they differ, shuffles, saves and checks the backup, then sends the writes paced at 20 a second with progress. Keep-order moves carry the latest `snapshot_id`, cancel works between moves and the `snapshot_id` is checked every 50 moves for another editor; fast mode can't stop halfway without leaving the playlist short, so cancel only works before its first write. Any failure once a write may have landed ends the run with Undo offered rather than a guess. Then it reads the playlist back and verifies it. Undo writes the newest backup back in the chosen mode without saving a new one. The cache forgets the playlist after any write (M4) |
| `shuffle/verify.py` | After the last write, compares the playlist as read back with what the plan meant to leave: the same songs as a multiset, the same count and the planned order. The result holds counts only, never URIs (M4) |
| `spotify/errors.py` | The errors the app shows the user: `SignInRequired`, `AccessDenied`, `NotOwner`, `RateLimited`, `SpotifyUnavailable` and `RequestRejected`. Messages quote only the status and Spotify's reason code (M2) |
| `storage/paths.py` | Finds `%LOCALAPPDATA%\FairShuffle` (logs) and `%APPDATA%\FairShuffle` (backups, settings) |
| `storage/backups.py` | Saves a playlist's order before every shuffle to `%APPDATA%\FairShuffle\backups` (D13): playlist ID, `snapshot_id`, time and each entry's URI, kind and local-file flag, nothing about the account. Writes a temp file and swaps it in, reads it back and checks it, and keeps the newest 10 per playlist. Refuses damaged, oversized or tampered files and playlist IDs that aren't plain base62, and logs no path. Gives the reorder target for a keep-order Undo (M4) |
| `storage/logging_setup.py` | Rotating log files (1 MB, five old files kept). Before a line is written, Authorization headers, Bearer tokens, `code` and any field whose name ends in `token`, `secret`, `verifier` or `client_id` are masked in any letter case, along with exact values such as the Client ID that code registers with `mask_secret()`. The home folder is written as `%USERPROFILE%` so the Windows user name stays out of paths under it. Qt's own warnings and uncaught errors go to the same file |

## Components (planned for M1 to M9)


```
              Windows notification area (hidden icons flyout)
                                 |
  +------------------------------v-------------------------------+
  | fairshuffle.ui        tray.py  picker.py  progress.py         |
  | (PySide6, main thread) about.py  theme.py                     |
  +------+--------------------+-------------------+---------------+
         | Qt signals         | Qt signals        |
  +------v----------+  +------v---------------+  +v----------------------+
  | fairshuffle.auth|  | fairshuffle.shuffle  |  | fairshuffle.storage   |
  | pkce.py         |  | engine.py   (pure)   |  | paths.py              |
  | loopback.py     |  | planner.py  (pure)   |  | settings.py           |
  | oauth.py        |  | runner.py   (worker) |  | backups.py            |
  | token_store.py  |  | verify.py   (pure)   |  | logging_setup.py      |
  +------+----------+  +------+---------------+  +-----------------------+
         |                    |
  +------v--------------------v-----------------+
  | fairshuffle.spotify                         |
  | client.py  playlists.py  models.py          |
  | errors.py  ratelimit.py                     |
  +---------------------+-----------------------+
                        | HTTPS
         accounts.spotify.com     api.spotify.com

  Refresh token -> Windows Credential Manager via keyring (service "FairShuffle")
```

## Repository layout (planned; M1 has `app.py`, `ui/tray.py`, `ui/about.py` and `storage/`)

```
fairshuffle/
  CLAUDE.md  README.md  LICENSE (MIT)  CHANGELOG.md
  pyproject.toml  uv.lock  .python-version
  .gitignore  .env.example
  .claude/   settings.json  hooks/format_python.py  agents/  skills/
  .github/   workflows/ci.yml  workflows/secret-scan.yml  ISSUE_TEMPLATE/  pull_request_template.md
  .pre-commit-config.yaml   gitleaks, ruff and hygiene hooks before every commit (D23)
  docs/      planning/  architecture.md  spotify-setup.md  screenshots/
  assets/    icons/ (original tray icon, light and dark)
  src/fairshuffle/
    __init__.py         version string
    __main__.py         entry point for python -m fairshuffle and the fairshuffle.exe launcher
    app.py              starts logging, builds QApplication, single-instance guard, wires modules together
    config.py           reads SPOTIFY_CLIENT_ID and SPOTIFY_REDIRECT_URI (env or .env in development)
    ui/
      tray.py           QSystemTrayIcon, menu, tooltip, notifications
      picker.py         playlist picker (shape decided in D11)
      progress.py       progress and cancel while a shuffle runs
      about.py          About dialog (version, license, Spotify attribution)
      theme.py          follows Windows light or dark mode (Phase 7)
    auth/
      pkce.py           code_verifier, S256 code_challenge, state (pure functions)
      loopback.py       one-shot HTTP listener on 127.0.0.1 for the sign-in callback
      oauth.py          authorize URL, code exchange, refresh, invalid_grant handling
      token_store.py    save, load and delete the refresh token (D10)
    spotify/
      client.py         HTTP session: auth header, 401 refresh-and-retry, error mapping
      ratelimit.py      pacing, Retry-After, both 429 shapes, backoff for 5xx and drops
      playlists.py      list playlists, read items, reorder, replace
      models.py         dataclasses: Playlist, PlaylistItem, Snapshot
      errors.py         SignInRequired, NotOwner, RateLimited, SpotifyUnavailable
    shuffle/
      engine.py         Fisher-Yates with secrets.SystemRandom (random source injectable for tests)
      planner.py        target order into a list of reorder (or replace) operations
      runner.py         applies a plan in a worker thread with progress, cancel and snapshot tracking
      verify.py         re-reads the playlist and proves nothing was lost or duplicated
    storage/
      paths.py          %APPDATA%\FairShuffle and %LOCALAPPDATA%\FairShuffle
      settings.py       settings.json (no secrets)
      backups.py        backup before every shuffle, restore for undo (D13)
      logging_setup.py  rotating log files with a redaction filter
  tests/
    conftest.py         shared fixtures, fake client ID, in-memory keyring
    fakes/
      fake_spotify.py   in-memory playlist API: paging, snapshot_id, reorder and replace semantics, 429 injection
    fixtures/           recorded JSON responses with all tokens redacted (no "token" in file names)
    unit/               one test file per module, for example test_pkce.py, test_engine.py
    integration/        runner plus fake_spotify end to end, loopback listener with a local client
```

## Threads (why the UI never freezes)

Qt draws the tray and windows on the main thread. Anything that waits on the network (sign-in, listing playlists, a shuffle) runs in a worker from `QThreadPool` and reports back through Qt signals. The networking analogy: the main thread is the control plane that must stay responsive; workers are the data plane doing the heavy forwarding. `engine.py`, `planner.py`, `verify.py` and `pkce.py` are pure functions with no I/O, so most tests need neither Qt nor a network.

## Sign-in flow mapped to modules (built in M2)

1. `ui/tray.py`: user clicks Sign in; `ui/account.py` starts `auth/sign_in.py` on a worker thread.
2. `auth/pkce.py`: creates `code_verifier`, `code_challenge` (S256) and `state`.
3. `auth/loopback.py`: listens on `127.0.0.1` only, on the port from `SPOTIFY_REDIRECT_URI`.
4. `auth/oauth.py`: opens the browser at `accounts.spotify.com/authorize` with the four playlist scopes and `user-read-private`.
5. `auth/loopback.py`: accepts one callback, checks `state`, shows "You can close this tab", stops.
6. `auth/oauth.py`: exchanges `code` plus `code_verifier` for tokens.
7. `auth/token_store.py`: refresh token to Credential Manager; access token stays in memory.
8. `auth/oauth.py` (`SpotifyAuth`): on 401 refresh once and retry; on `400 invalid_grant` delete the token and raise `SignInRequired`. `spotify/client.py` sends every API call through it.

Scopes are the four playlist scopes, `playlist-read-private`, `playlist-read-collaborative`, `playlist-modify-private` and `playlist-modify-public`, plus `user-read-private`. Spotify's scopes page lists `user-read-private` as the scope `GET /me` needs, and the docs don't say whether `display_name` comes back without it, so Derek chose to ask for it (P2-4). Its other fields (country, product, explicit content) are gone for development mode apps, so it adds nothing else. `user-read-email` is not asked for. If Spotify gives no name, the menu falls back to "Signed in to Spotify".

## Shuffle flow mapped to modules (planned for M3 and M4)

1. `ui/picker.py`: user picks a playlist.
2. `spotify/cache.py` and `spotify/playlists.py`: reads all items in pages of 50, or reuses them when the playlist's `snapshot_id` is unchanged. The items call itself carries no `snapshot_id`, so the shuffle compares it from `GET /playlists/{id}` before and after reading (P4-06).
3. `storage/backups.py`: writes the current order to `%APPDATA%\FairShuffle\backups\`.
4. `shuffle/engine.py` then `shuffle/planner.py`: random order, then the move list (D12).
5. `shuffle/runner.py`: applies moves through `spotify/ratelimit.py`; progress and cancel through `ui/progress.py`.
6. `shuffle/verify.py`: re-reads and compares item counts and URIs.
7. `ui/tray.py`: "Shuffled 342 songs. Play from track 1 with Spotify shuffle off and sort set to Custom order."

## Where data lives

| Data | Location | In Git? | Built in |
|------|----------|---------|----------|
| Spotify Client ID (development) | `.env` in the project folder | Never | M2 |
| Spotify Client ID (prototype .exe) | `.env` next to `FairShuffle.exe`, copied in by the user (P5-4) | Never; the build refuses to ship one | M5 |
| Refresh token | Windows Credential Manager, service `FairShuffle` | Never | M2 |
| Access token | Memory only | Never | M2 |
| Settings (no secrets) | `%APPDATA%\FairShuffle\settings.json` | No | M3 or later |
| Playlist backups | `%APPDATA%\FairShuffle\backups\` | No | M4 |
| Logs (secrets and home folder redacted) | `%LOCALAPPDATA%\FairShuffle\logs\` | No | M1 |

## Toolchain (D18 to D24 as answered)

| Tool | Version on 2026-10-20 (from `uv.lock` and the hook revs, except Python and uv) | Used for |
|------|----------------------------|----------|
| Python | 3.14 (`.python-version`; 3.14.8 locally) | the app |
| uv | 0.13.1 (installed in P0-3) | Python install, venv, dependencies, lockfile |
| PySide6-Essentials | 6.12.0 (released 2026-10-08) | tray, windows, local socket |
| ruff | 0.17.1 (P0-24) | format and lint, including the `S` security rules |
| pyright | 1.1.414 (with bundled Node) | type checking, same engine as the pyright-lsp plugin |
| pytest, pytest-qt, pytest-cov | 9.1.1, 4.5.0, 7.1.0 | tests and coverage |
| pre-commit | 4.7.0 | runs gitleaks, ruff and hygiene hooks before every commit |
| gitleaks | 8.30.1 | pre-commit hook and CI secret scan |
| PyInstaller | 6.22.3 (D25, in the `build` dependency group) | `scripts/build_exe.py` builds `dist/FairShuffle/` from `packaging/fairshuffle.spec` |

A sample project with the proposed `pyproject.toml` resolved and locked cleanly with uv on Python 3.14.8, and ruff and pyright ran clean on it.
