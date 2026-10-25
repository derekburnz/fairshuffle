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

Milestone M4 (v0.4.0) adds the shuffle engine: a Fisher-Yates shuffle with Windows' secure random source, a backup of the order before every shuffle, two ways to write the new order (fast, which rewrites the list in about 2 seconds, or keep order, which moves one song at a time so "date added" and local files survive) and a read-back check plus Undo. It was checked against the real Spotify on a test playlist: 10 shuffles and an Undo, all verified. There is no Shuffle button yet; the picker's Shuffle and Undo buttons arrive in M5.

The [roadmap](docs/planning/ROADMAP.md) lists every milestone and issue.

## How it will work

1. Sign in to Spotify once. FairShuffle uses Authorization Code with PKCE, so there is no client secret anywhere, and the refresh token is kept in Windows Credential Manager.
2. Pick a playlist you own or collaborate on.
3. FairShuffle backs up the current order, shuffles it with Fisher-Yates using a cryptographically secure random source, writes the new order and reads the playlist back to check nothing was lost or duplicated.
4. Play the playlist from track 1 in Spotify with shuffle off and the sort set to Custom order.

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

## How this project is run

FairShuffle is a solo portfolio project run like a team project:

- Every change goes through a pull request linked to an issue, with Conventional Commit messages and a squash merge.
- `main` is protected: a pull request merges only when the secret scan, lint and type checks and tests on Windows all pass.
- gitleaks scans for secrets before every commit and again in CI, and Dependabot keeps actions, Python packages and hooks current.
- Every design choice is recorded with its reason in [`docs/planning/DECISIONS.md`](docs/planning/DECISIONS.md).
- [Claude Code](https://claude.com/claude-code) helps build it, with project agents for security review, tests and docs in [`.claude/`](.claude/).

## License

[MIT](LICENSE)
