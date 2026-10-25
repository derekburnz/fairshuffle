# FairShuffle

[![CI](https://github.com/derekburnz/fairshuffle/actions/workflows/ci.yml/badge.svg)](https://github.com/derekburnz/fairshuffle/actions/workflows/ci.yml)
[![Secret scan](https://github.com/derekburnz/fairshuffle/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/derekburnz/fairshuffle/actions/workflows/secret-scan.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A Windows 11 tray app that gives a Spotify playlist a true Fisher-Yates shuffle. You pick one of your playlists, FairShuffle rewrites its order through the Spotify Web API, and you play it from track 1 with Spotify's own shuffle turned off.

## Why

Spotify's shuffle is not a plain random shuffle, and people with large playlists notice the same songs coming up again and again. FairShuffle sidesteps it: every order of the playlist is equally likely, and the order is written into the playlist itself, so it works on every device you play from.

## Status

Early development. Milestone M1 (v0.1.0) built the app's frame:

- An icon in the notification area (the hidden icons flyout behind `^` on the taskbar) with About and Quit.
- One copy runs per Windows user. Launching it again points you at the icon that is already there.
- Rotating log files in `%LOCALAPPDATA%\FairShuffle\logs`, with tokens, sign-in codes, known secret values and your home folder path masked before a line is written.

Milestone M2 (v0.2.0) adds signing in to Spotify from the tray menu, which shows "Signed in as" with your Spotify name. You register your own Spotify app first ([setup guide](docs/spotify-setup.md)); after that, Sign in opens your browser once and FairShuffle stays signed in across restarts until you pick Sign out or the six-month sign-in runs out.

Milestone M3 (v0.3.0) adds the playlist picker. Left-click the tray icon, or pick **Shuffle a playlist…** in its menu, and a small window lists every playlist you own or collaborate on, with item counts, a search box and Refresh ([screenshot](docs/screenshots/picker-window.png)). Playlists you only follow are left out, because Spotify only lets their owner and collaborators reorder them.

Milestone M4 (v0.4.0) adds the shuffle engine: a Fisher-Yates shuffle with Windows' secure random source, a backup of the order before every shuffle, two ways to write the new order (fast, which rewrites the list in about 2 seconds, or keep order, which moves one song at a time so "date added" and local files survive) and a read-back check plus Undo. It was checked against the real Spotify on a test playlist: 10 shuffles and an Undo, all verified.

Milestone M5 (v0.5.0) makes it usable from the tray: Shuffle, Undo and Cancel in the picker, a "Keep date added (slower)" box, questions before anything is lost and a notice when the shuffle is done ([screenshot](docs/screenshots/picker-shuffle.png)). It also adds a FairShuffle.exe build, published as a pre-release zip.

The [roadmap](docs/planning/ROADMAP.md) lists every milestone and issue.

## Using FairShuffle

### Before the first run

1. **Register your own Spotify app** (about five minutes, once). FairShuffle signs in with Authorization Code and PKCE, so there is no client secret, but Spotify still needs a Client ID that names your copy of the app. The [setup guide](docs/spotify-setup.md) walks through it. You need Spotify Premium on the account that owns the app.
2. **Put the Client ID in a `.env` file.** Running from source, that is `.env` in the project folder. Running the built FairShuffle.exe, copy the same `.env` next to `FairShuffle.exe`. Never share that file.
3. **Start FairShuffle**: `uv run python -m fairshuffle` from source (see [Developer setup](#developer-setup)), or double-click `FairShuffle.exe`. Nothing opens; an icon appears in the hidden icons flyout behind `^` on the taskbar. Drag it onto the taskbar if you want it always visible.

### Sign in

Right-click the icon and pick **Sign in to Spotify…**. Your browser opens Spotify's sign-in page; approve FairShuffle and close the tab when it says you're done. The menu then reads "Signed in as" with your Spotify name. FairShuffle stays signed in across restarts until you pick **Sign out** or six months pass, after which it asks you to sign in again.

### Shuffle a playlist

1. Left-click the icon, or pick **Shuffle a playlist…** in its menu. The picker lists every playlist you own or collaborate on. Playlists you only follow can't be reordered, so they aren't listed.
2. Pick a playlist. Type in the search box to narrow a long list.
3. Choose how to write the new order:
   - **Fast (the box unticked, the default):** rewrites the list in a few seconds. Every song's "date added" becomes now, and local files can't be written back, so FairShuffle asks first if the playlist has any.
   - **Keep date added (slower), ticked:** moves the songs one at a time, so dates and local files stay as they were. About 20 seconds for 60 songs. FairShuffle remembers the choice.
4. Press **Shuffle**. The line under the list shows progress; **Cancel** stops a keep-order shuffle between moves, or a fast one before it starts writing.
5. When it's done, a notice says "Shuffled" with the playlist's name.

Before every shuffle FairShuffle saves the current order to `%APPDATA%\FairShuffle\backups`, and afterwards it reads the playlist back to check every song is still there in the new order.

### Play it

Open the playlist in Spotify, **turn Spotify's shuffle off** and start from **track 1**. If the songs still show in the old order, set the playlist's sort to **Custom order**. The new order is saved in the playlist itself, so it plays the same on your phone, your PC and any speaker.

### Undo

Pick the playlist and press **Undo** to put back the order from before its last shuffle. Undo is greyed out for a playlist FairShuffle has no backup of. If songs were added since the shuffle, a fast Undo asks before removing them, and if a shuffle stops partway (a lost connection, say), FairShuffle offers Undo straight away.

### If something goes wrong

- **"Spotify app not set up yet"**: the Client ID is missing; check step 2 above.
- **The sign-in page says the redirect URI is invalid**: the Redirect URI in the Spotify dashboard and in `.env` must both be exactly `http://127.0.0.1:8888/callback`.
- **Windows blocks FairShuffle.exe**: the prototype isn't code signed yet, so Smart App Control or SmartScreen may stop it. Running from source works in the meantime.
- **Anything else**: the log is in `%LOCALAPPDATA%\FairShuffle\logs\fairshuffle.log`. Tokens, codes and your home folder are masked before anything is written there.

[`docs/architecture.md`](docs/architecture.md) describes the parts and the sign-in and shuffle flows.

## Developer setup

FairShuffle is Windows-only for now. You need [Git for Windows](https://git-scm.com/download/win), [uv](https://docs.astral.sh/uv/) and [gitleaks](https://github.com/gitleaks/gitleaks), which the pre-commit hook runs before every commit:

```powershell
winget install --id astral-sh.uv -e
winget install --id Gitleaks.Gitleaks -e
```

Then clone the repo and set it up:

```powershell
git clone https://github.com/derekburnz/fairshuffle.git
cd fairshuffle
uv sync                     # installs Python 3.14 if needed, then every dependency from uv.lock
uv run pre-commit install   # runs gitleaks, ruff and hygiene checks before every commit
```

Run the app and the same checks CI runs:

```powershell
uv run python -m fairshuffle             # the icon appears under ^ on the taskbar
uv run python -m fairshuffle --version
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest --cov=fairshuffle
```

If you use Claude Code with this repo, its `pyright-lsp` plugin needs pyright installed for your user, at the version `uv.lock` pins:

```powershell
uv tool install "pyright[nodejs]==1.1.414"
```

From M2 on, the app reads your Spotify Client ID from a `.env` file. [`docs/spotify-setup.md`](docs/spotify-setup.md) walks through registering your own Spotify developer app and filling in `.env`. `.env` is gitignored; never commit it.

To try the shuffle against the real Spotify before the picker has its buttons, `scripts/live_shuffle_test.py` works on one playlist only: the one you own named exactly "Shuffle Test". Make one with about 30 songs, sign in from the tray, then quit FairShuffle so the script has the saved sign-in to itself (it refuses to start while the tray app runs, and it takes at most 100 songs):

```powershell
uv run python scripts/live_shuffle_test.py          # finds the playlist; writes nothing
uv run python scripts/live_shuffle_test.py --run    # 5 fast and 5 keep-order shuffles, then an Undo
```

Each step is read back and checked. Fast mode resets the songs' "date added", which is why it runs on a playlist made for testing.

### Building FairShuffle.exe

PyInstaller (D25) bundles Python, Qt and the app into one folder that runs without Python installed. It builds for the system it runs on, so run it on Windows:

```powershell
uv run --group build python scripts/build_exe.py         # makes dist\FairShuffle\FairShuffle.exe
uv run --group build python scripts/build_exe.py --zip   # also dist\FairShuffle-<version>-windows-x64.zip
```

The build reads `packaging/fairshuffle.spec`, takes about a minute and starts from a clean folder each time. To run the built app, copy your `.env` into `dist\FairShuffle` next to `FairShuffle.exe` (P5-4); each build clears the folder, so copy it again after rebuilding. The folder and the zip never contain your `.env`: the build stops if it finds one. Keep the folder somewhere only you can write to, such as under your user profile, because anyone who can change that `.env` can point the app at another Spotify app. The .exe isn't code signed yet (D16), so Smart App Control or SmartScreen may block it.

CI builds the same folder on Windows (`.github/workflows/prerelease.yml`) whenever a pull request touches the build, and smoke tests the .exe. When a `v*` tag is pushed (Derek's call), it checks the tag matches the app version, then publishes the zip and its SHA-256 checksum as a GitHub pre-release, or adds them to a release already written for that tag.

## How this project is run

FairShuffle is a solo portfolio project run like a team project:

- Every change goes through a pull request linked to an issue, with Conventional Commit messages and a squash merge.
- `main` is protected: a pull request merges only when the secret scan, lint and type checks and tests on Windows all pass.
- gitleaks scans for secrets before every commit and again in CI, and Dependabot keeps actions, Python packages and hooks current.
- Every design choice is recorded with its reason in [`docs/planning/DECISIONS.md`](docs/planning/DECISIONS.md).
- [Claude Code](https://claude.com/claude-code) helps build it, with project agents for security review, tests and docs in [`.claude/`](.claude/).

## License

[MIT](LICENSE)
