# FairShuffle: final roadmap (Stage C)

Status: **APPROVED by Derek on 2026-10-09.** Tooling cards D18 to D24 answered 2026-10-13. Stage C is complete. Drafted 2026-10-09 from the Stage B answers (D1 to D8 in `DECISIONS.md`), the Spotify API re-check of 2026-10-08 and a spot check on 2026-10-09. Nothing has been created on GitHub, installed or coded.

When Derek approves, this file replaces sections 3 and 8 of `PROJECT_PLAN.md` (those sections get a one-line pointer here) and Phase 0 can start.

## Contents

1. What Stage C changed
2. New decisions from Stage C (D18 to D25)
3. Architecture with real module names (replaces PROJECT_PLAN section 3)
4. Phase 0 checklist (setup, no issues yet)
5. Milestones and issue list (Phases 1 to 8)
6. Starter-kit changes
7. Facts this roadmap relies on, and when they were checked

---

## 1. What Stage C changed

The plan was language-neutral. With Python and PySide6 chosen it now names every module, lists 52 issues across 8 milestones and ships tailored starter-kit files. The app is called FairShuffle everywhere: repo `fairshuffle`, Python package `fairshuffle`, Windows data folders `%APPDATA%\FairShuffle` and `%LOCALAPPDATA%\FairShuffle`, Credential Manager service name `FairShuffle`.

Turning the plan into Python raised seven tooling choices the plan never asked (D18 to D24) plus one for Phase 5 (D25). Each is in section 2 with Derek's answer. The rest of this file follows those answers.

The milestones, versions, phase goals and the D9 to D17 phase cards are unchanged from PROJECT_PLAN section 8.

---

## 2. New decisions from Stage C

Derek answered on the decision page on 2026-10-13: **D18 A, D19 A, D20 A, D21 A, D22 A, D23 C, D24 B.** D23 was answered as "whatever is closest to working as a software developer in industry", which is option C: most professional Python teams commit a `.pre-commit-config.yaml`. Answers are in the `DECISIONS.md` log.

| ID | Decision | Options | Recommendation | Asked |
|----|----------|---------|----------------|-------|
| D18 | Python version | A. 3.14 (current bug-fix branch, supported to Oct 2030) B. 3.13 (security fixes only) C. 3.15 once it is final | A: newest stable; PySide6 6.12 and PyInstaller support it; tested here with 3.14.8 | Stage C |
| D19 | Project and dependency manager | A. uv B. pip with venv and requirements.txt C. Poetry | A: one tool installs Python itself, creates the venv and writes a lockfile so CI and your PC get identical versions | Stage C |
| D20 | Code quality tools | A. ruff + pyright + pytest B. ruff + mypy + pytest C. ruff + pytest, no type checker | A: pyright is the engine of the pyright-lsp plugin from D7, so Claude, your editor and CI report the same type errors | Stage C |
| D21 | Qt package | A. PySide6-Essentials B. full PySide6 | A: has everything we use (tray, widgets, local socket); 82 MB wheel instead of 123 MB; the packaged app is about the same size either way | Stage C |
| D22 | Source layout | A. `src/fairshuffle/` (src layout) B. `fairshuffle/` at the repo root | A: the packaging guide's recommended layout; tests always run against the installed package, which catches packaging mistakes early | Stage C |
| D23 | Where auto-formatting runs | A. Claude hook + git pre-commit check + CI B. Claude hook + CI only C. the pre-commit framework manages gitleaks and ruff | A: Claude's edits are formatted instantly, your own edits are caught before commit and CI is the final gate; no extra tool | Stage C |
| D24 | CI runners | A. lint on Ubuntu, tests on Windows B. everything on Windows C. everything on Ubuntu | A: the app is Windows-only, so tests run on Windows; lint is faster on Ubuntu. Public repos get free Actions minutes on both | Stage C |
| D25 | Build tool for the .exe | A. PyInstaller B. Nuitka | Asked at the start of Phase 5 with a size and antivirus comparison | Phase 5 |

Library picks that belong to existing phase cards stay there: the HTTP library is part of D9 (Phase 2) and keyring is D10 (Phase 2).

---

## 3. Architecture with real module names

Replaces PROJECT_PLAN section 3. Same boxes as before, now mapped to Python modules. From M1 on, [`docs/architecture.md`](../architecture.md) is the living copy that follows the code; this section stays as the approved plan.

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

### 3.1 Repository layout

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
    app.py              builds QApplication, single-instance guard, wires modules together
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

### 3.2 Threads (why the UI never freezes)

Qt draws the tray and windows on the main thread. Anything that waits on the network (sign-in, listing playlists, a shuffle) runs in a worker from `QThreadPool` and reports back through Qt signals. The networking analogy: the main thread is the control plane that must stay responsive; workers are the data plane doing the heavy forwarding. `engine.py`, `planner.py`, `verify.py` and `pkce.py` are pure functions with no I/O, so most tests need neither Qt nor a network.

### 3.3 Sign-in flow mapped to modules

1. `ui/tray.py`: user clicks Sign in.
2. `auth/pkce.py`: creates `code_verifier`, `code_challenge` (S256) and `state`.
3. `auth/loopback.py`: listens on `127.0.0.1` only, on the port from `SPOTIFY_REDIRECT_URI`.
4. `auth/oauth.py`: opens the browser at `accounts.spotify.com/authorize` with the four playlist scopes.
5. `auth/loopback.py`: accepts one callback, checks `state`, shows "You can close this tab", stops.
6. `auth/oauth.py`: exchanges `code` plus `code_verifier` for tokens.
7. `auth/token_store.py`: refresh token to Credential Manager; access token stays in memory.
8. `spotify/client.py`: on 401 refresh once; on `400 invalid_grant` delete the token and raise `SignInRequired`.

Scopes stay least privilege: `playlist-read-private`, `playlist-read-collaborative`, `playlist-modify-private`, `playlist-modify-public`. Open question for Phase 2 (issue P2-02): the `GET /me` reference page lists `user-read-private` and `user-read-email` as scopes, but they only unlock deprecated fields (email, country, product). The plan assumes `id` and `display_name` come back without them; the researcher confirms before P2-08.

### 3.4 Shuffle flow mapped to modules

1. `ui/picker.py`: user picks a playlist.
2. `spotify/playlists.py`: reads all items in pages of 50 and records `snapshot_id`.
3. `storage/backups.py`: writes the current order to `%APPDATA%\FairShuffle\backups\`.
4. `shuffle/engine.py` then `shuffle/planner.py`: random order, then the move list (D12).
5. `shuffle/runner.py`: applies moves through `spotify/ratelimit.py`; progress and cancel through `ui/progress.py`.
6. `shuffle/verify.py`: re-reads and compares item counts and URIs.
7. `ui/tray.py`: "Shuffled 342 songs. Play from track 1 with Spotify shuffle off and sort set to Custom order."

### 3.5 Where data lives

| Data | Location | In Git? |
|------|----------|---------|
| Spotify Client ID (development) | `.env` in the project folder | Never |
| Refresh token | Windows Credential Manager, service `FairShuffle` | Never |
| Access token | Memory only | Never |
| Settings (no secrets) | `%APPDATA%\FairShuffle\settings.json` | No |
| Playlist backups | `%APPDATA%\FairShuffle\backups\` | No |
| Logs (tokens redacted) | `%LOCALAPPDATA%\FairShuffle\logs\` | No |

### 3.6 Toolchain (D18 to D24 as answered)

| Tool | Version checked 2026-10-09 | Used for |
|------|----------------------------|----------|
| Python | 3.14.8 | the app |
| uv | 0.13.1 (checked 2026-10-14, P0-3) | Python install, venv, dependencies, lockfile |
| PySide6-Essentials | 6.12.0 (released 2026-10-08) | tray, windows, local socket |
| ruff | 0.17.0 (checked 2026-10-14) | format and lint, including the `S` security rules |
| pyright | 1.1.414 (with bundled Node) | type checking, same engine as the pyright-lsp plugin |
| pytest, pytest-qt, pytest-cov | 9.1.1, 4.5.0, 7.1.0 | tests and coverage |
| pre-commit | 4.6.2 | runs gitleaks, ruff and hygiene hooks before every commit |
| gitleaks | 8.30.1 | pre-commit hook and CI secret scan |

A sample project with the proposed `pyproject.toml` resolved and locked cleanly with uv on Python 3.14.8, and ruff and pyright ran clean on it.

---

## 4. Phase 0 checklist (setup)

Runs on Derek's PC in `C:\Projects\playlist-shuffler` through Remote Control. Claude asks before every install, every GitHub change and every push. Phase 0 has no GitHub issues because the repo does not exist yet; its last step creates the issues in section 5.

1. **Fix the folder layout** (ask first): move the package contents up one level so `CLAUDE.md` sits at the folder root, then sync the Stage B log and this roadmap into the PC copies of `DECISIONS.md`, `CLAUDE.md` and `PROJECT_PLAN.md`.
2. **Check and install tools**, one card per install: Git for Windows, GitHub CLI, gitleaks, uv (then `uv python install 3.14`). Claude confirms the winget package IDs at install time.
3. **GitHub account steps Derek does himself:** 2FA, "Keep my email addresses private", copy the noreply address, `gh auth login`, then `git config --global` name, noreply email and `init.defaultBranch main`.
4. **Copy approved starter-kit files** into place, one sentence each: `.gitignore`, `.gitattributes` (new, P0-4), `.env.example`, `.claude/` (settings, hook, agents, skills), `.github/` (templates, `secret-scan.yml`), `.pre-commit-config.yaml` and `pyproject.toml`. `ci.yml` waits for Phase 1.
5. **First commit and repo:** `git init`, `uv sync --no-install-project` (plain `uv sync` needs `src/fairshuffle`, which P1-01 adds), `uv run --no-sync pre-commit install` (Claude explains what it hooks into), commit `chore: initial project scaffolding and planning docs`, create public repo `fairshuffle` with the MIT license (ask), push (ask). Attach the repo to this project.
6. **Install approved plugins and connectors** one at a time with a harmless demo each: pyright-lsp, security-guidance, explanatory-output-style, pr-review-toolkit, GitHub MCP (fine-grained token in an environment variable only), Context7.
7. **Demo each agent and skill once:** security-reviewer on the first commit, spotify-api-researcher on one endpoint, decision-card, phase-report.
8. **Repo settings:** protect `main` (PR required, `gitleaks` check required, no force push), secret scanning and Dependabot alerts, Issues on, Projects board "Roadmap", labels, milestones M1 to M8, issues from section 5.
9. **Delete the starter-kit folder** (ask) so each file exists once.

DoD: repo live and public, `main` protected, secret scan green, Derek can describe each tool in one sentence.

---

## 5. Milestones and issue list

IDs such as P2-03 are planning IDs; GitHub assigns the real numbers when Phase 0 creates the issues. Labels: `type:feature`, `type:bug`, `type:docs`, `type:chore`, `type:test`, `type:ci` and `priority:high/med/low`. Each issue becomes one branch and one PR through the ship-change skill. Issues that are only a Decision Card are labelled `type:decision` and close when the answer is logged.

Every PR also meets the shared definition of done: CI green, security-reviewer PASS, tests for new behaviour, no secrets or personal paths, docs updated when behaviour changes. Claude then squash-merges it and tells Derek (P0-21).

### M1: Creation (v0.1.0)

Goal: the app starts, shows a tray icon in the hidden icons flyout and quits cleanly.

| ID | Title | Description | Acceptance criteria |
|----|-------|-------------|---------------------|
| P1-01 | chore: Python project scaffold | `pyproject.toml`, src layout, `uv.lock`, `.python-version` | `uv sync` works on a clean clone; `uv run python -m fairshuffle --version` prints 0.1.0; ruff, pyright and pytest settings live in `pyproject.toml` |
| P1-02 | ci: lint, type check and test workflow | Copy `ci.yml` into place and make it a required check | Workflow runs on PRs and `main`; format, lint, pyright and pytest jobs pass; `lint and type check (Windows)` and `tests (Windows)` added as required checks on `main` |
| P1-03 | test: pytest and pytest-qt harness | `tests/` tree, `conftest.py`, first smoke test | A headless test creates the tray icon; coverage prints in CI; fake client ID only |
| P1-04 | feat(ui): tray icon with About and Quit | QSystemTrayIcon with tooltip, placeholder original icon | Icon appears under `^` on Windows 11; tooltip reads FairShuffle; About shows version and MIT; Quit removes the icon and exits with code 0; menu works by keyboard |
| P1-05 | feat: single-instance guard | Second launch hands over to the running copy (QLocalServer) | Starting twice leaves one icon; the second process exits; covered by a test |
| P1-06 | feat(storage): logging with a redaction filter | Rotating logs in `%LOCALAPPDATA%\FairShuffle\logs` | Bearer tokens, `code=`, `refresh_token`, `access_token` and the client ID are masked; unit tests feed fake values and assert they never reach the file |
| P1-07 | docs: README skeleton and architecture notes | What it is, status, developer setup, link to `docs/planning` | README renders on GitHub; `docs/architecture.md` holds section 3 of this roadmap |

DoD: Derek runs it from source, sees the icon under `^`, Quit works, CI green.

### M2: Connect to Spotify (v0.2.0)

Goal: sign in and sign out securely.

| ID | Title | Description | Acceptance criteria |
|----|-------|-------------|---------------------|
| P2-01 | docs: Spotify developer app setup guide | `docs/spotify-setup.md`; Derek creates the app (Premium owner, name without "Spotify", Redirect URI `http://127.0.0.1:8888/callback`) | Guide followed once by Derek; Client ID only in his `.env`; nothing of his in the repo |
| P2-02 | chore: verify auth facts, then D9 and D10 | spotify-api-researcher re-checks the auth, `/me` and playlist pages; then the D9 and D10 cards | Findings dated in the spotify-api-notes skill; D9 and D10 logged |
| P2-03 | feat(auth): PKCE helpers | verifier, S256 challenge, state | RFC 7636 appendix B test vector passes; verifier length 43 to 128 from `secrets` |
| P2-04 | feat(auth): one-shot loopback listener | `http.server` bound to 127.0.0.1 on the redirect port | Accepts one `/callback`; wrong `state` rejected; stops after one request or a timeout; never binds 0.0.0.0 (test checks the socket address) |
| P2-05 | feat(auth): code exchange and refresh | Token endpoint calls through the D9 HTTP choice | Mocked tests: success, 401 then one refresh, `400 invalid_grant` raises SignInRequired with no retry; no token text in logs |
| P2-06 | feat(auth): refresh token storage | `token_store.py` per D10 | Save, load and delete under service FairShuffle; tests use an in-memory keyring backend |
| P2-07 | feat(spotify): API client core | Auth header, error mapping, `ratelimit.py` | Tests: 429 with `Retry-After` only, 429 with `QUOTA_EXCEEDED` JSON, 5xx backoff, network drop, 403 mapped to NotOwner |
| P2-08 | feat(ui): sign in, sign out and "Signed in as" | Tray menu wiring | Restart keeps the session without a browser; sign out removes the Credential Manager entry; expired session shows "Sign in again" |

DoD: as PROJECT_PLAN Phase 2.

### M3: See your playlists (v0.3.0)

Goal: list the playlists the app can shuffle. Read-only, so nothing can be damaged.

| ID | Title | Description | Acceptance criteria |
|----|-------|-------------|---------------------|
| P3-01 | chore: D11 tray UI shape | ui-designer mockups, then the D11 card | D11 logged with the chosen mockup in `docs/screenshots/` |
| P3-02 | feat(spotify): list editable playlists | `GET /me/playlists`, limit 50, follow `next` | Keeps only playlists owned by the user or marked collaborative; count from `items.total` (not the deprecated `tracks.total`); tests for 0, 1 and 120 playlists |
| P3-03 | feat(spotify): read all playlist items | `GET /playlists/{id}/items`, pages of 50 | Keeps URI, position, local-file flag; handles episodes, local files and null (unavailable) items; fixture covers all four |
| P3-04 | feat(ui): playlist picker | Per D11, with item counts and Refresh | Derek's real playlists appear; keyboard navigable; long names truncated with a tooltip |
| P3-05 | feat: playlist cache keyed by snapshot_id | Skip refetching unchanged playlists | Unchanged `snapshot_id` makes no item calls; test proves it |
| P3-06 | feat(ui): empty, error and large-list states | 0 playlists, API error, 200+ playlists | Each state has a message and a test |

### M4: True shuffle engine (v0.4.0)

Goal: shuffle a playlist correctly and safely.

| ID | Title | Description | Acceptance criteria |
|----|-------|-------------|---------------------|
| P4-01 | chore: D12 strategy and D13 backup | Decision Cards; consider switching to the Learning style for P4-02 | D12 and D13 logged |
| P4-02 | feat(shuffle): Fisher-Yates engine | `engine.py`, `secrets.SystemRandom` by default, injectable source | Output is a permutation (duplicates, local files, episodes included); 0, 1, 2 and 10,000 items; chi-square test over the 24 orders of 4 items passes |
| P4-03 | feat(shuffle): plan builder | Target order to reorder moves (plus replace chunks if D12 is B or D) | Replaying the plan on a simulated list gives the target exactly; no-op moves skipped; at most N minus 1 moves |
| P4-04 | test: fake Spotify playlist simulator | `tests/fakes/fake_spotify.py` | Implements `range_start`, `insert_before`, `range_length`, `snapshot_id` and 429 injection the way the reference page describes; has its own tests |
| P4-05 | feat(storage): backup before every shuffle | `backups.py`, plus restore if D13 is A | Backup written and read back before the first API write; restore returns the original order on the simulator |
| P4-06 | feat(shuffle): plan runner | Worker thread, pacing, Retry-After, progress, cancel | Cancel stops cleanly between moves; a changed `snapshot_id` from another editor stops the run with a clear message |
| P4-07 | feat(shuffle): verify after shuffle | `verify.py` | Re-read playlist has the same multiset of URIs and count; mismatch offers restore |
| P4-08 | chore: live test on the Shuffle Test playlist | Derek creates a 30-song test playlist and says go | 10 verified runs logged in the PR; first real playlist only after Derek asks |

### M5: Prototype (v0.5.0, pre-release)

| ID | Title | Description | Acceptance criteria |
|----|-------|-------------|---------------------|
| P5-01 | feat: end-to-end wiring and completion notice | Picker to shuffle to notification | Works from the tray without a terminal; notice carries the "track 1, shuffle off, Custom order" tip |
| P5-02 | chore: D25 build tool and packaging script | Decision Card, then a build script | `uv run` command produces a runnable folder or exe on Derek's PC |
| P5-03 | ci: pre-release build on tag | Windows build job on `v*` tags, attaches the zip to a GitHub pre-release | Tag `v0.5.0` (Derek approves) produces a pre-release with the zip |
| P5-04 | docs: how to use FairShuffle | README usage section | A first-time reader can sign in and shuffle by following it |
| P5-05 | chore: real-use notes and D14 backlog picks | Derek uses it for a few days; Claude helps write issues | Issues filed; D14 logged |

### M6: Bug fixes and hardening (v0.6.x)

Bugs from M5 are added here as they are found, each with a failing test first.

| ID | Title | Description | Acceptance criteria |
|----|-------|-------------|---------------------|
| P6-01 | fix: playlist edited during a shuffle | Snapshot mismatch handling | Simulator test edits mid-run; the app stops, verifies and offers restore |
| P6-02 | fix: network drop and PC sleep mid-run | Resume or restore after a broken connection | Simulator test cuts the connection at move 100 of 300; final state is correct or restored |
| P6-03 | fix: 429 storms | Long or repeated `Retry-After`, quota errors | User sees "Spotify asked us to slow down" with time left; no tight retry loop |
| P6-04 | fix: lapsed Premium and other 403s | Clear messages for each 403 cause | Spotify's current 403 bodies are checked first (Rule 4); each case has a test and a message |
| P6-05 | test: large playlist (1,000+ items) | Performance and call count | Planner and runner tests at 1,000 and 10,000 items within agreed limits |
| P6-06 | chore: full log and leak review | security-reviewer over logs, fixtures and history | PASS recorded in the issue |

### M7: Visual polish (v0.9.0)

| ID | Title | Description | Acceptance criteria |
|----|-------|-------------|---------------------|
| P7-01 | feat(ui): original tray icon | ui-designer offers 2 or 3 options as a card | Light and dark variants in `assets/icons/`; nothing resembling the Spotify logo |
| P7-02 | feat(ui): follow Windows light and dark mode | `theme.py` | Switching Windows theme updates the icon and windows |
| P7-03 | feat(ui): settings window and menu wording | Options from D14 picks | Derek approves each screen on a card |
| P7-04 | feat(ui): progress window polish | Clear progress, time left, cancel | Derek approves the screen |
| P7-05 | fix(ui): accessibility pass | Keyboard, contrast, screen reader names | Every control reachable by keyboard and named for Narrator |
| P7-06 | docs: screenshots and demo GIF | For the README | Committed under `docs/screenshots/` with no personal data visible |

### M8: Final project (v1.0.0)

| ID | Title | Description | Acceptance criteria |
|----|-------|-------------|---------------------|
| P8-01 | chore: D15, D16 and D17 | Distribution, signing, Client ID in release builds | All three logged |
| P8-02 | feat: first-run Client ID setup | Only if D17 is A | New user enters their own Client ID once; stored in settings, never in the repo |
| P8-03 | ci: release workflow | Tagged build attaches the D15 format to a GitHub Release | `v1.0.0` tag (Derek approves) publishes the release |
| P8-04 | docs: final README, CHANGELOG and privacy note | Demo GIF, how it works, architecture diagram, bring-your-own-Client-ID guide | A fresh Windows user installs and shuffles by following the README |
| P8-05 | chore: repo presentation | Description, topics, social preview, pin on profile | Done in GitHub settings with Derek |
| P8-06 | docs: resume bullets and talking points | docs-writer drafts; Derek edits | Kept outside the repo unless Derek chooses to commit them |

---

## 6. Starter-kit changes

Phase 0 copied these files into place, and #58 deleted the starter-kit folder (P0-22) so each file exists once. `ci.yml` waits for issue #4, which restores it from Git history. Originals are saved in the project's shared folder at `setup/stage-c/starter-kit-originals/`.

| File | Change |
|------|--------|
| `.gitignore` | Python section only (venv, caches, coverage, `build/`, `dist/`, `*.egg-info/`); C# and Tauri sections removed; secrets section untouched |
| `.claude/settings.json` | Adds a PostToolUse hook on Edit and Write that runs `.claude/hooks/format_python.py` through `uv run` |
| `.claude/hooks/format_python.py` | New. For each edited `.py` file inside the project: `ruff check --fix`, then `ruff format`; anything ruff cannot fix goes back to Claude (exit code 2) so it fixes it at once. Skips quietly until ruff is installed in P1-01. Tested here on a messy file: unused import removed, file formatted, undefined name reported |
| `.pre-commit-config.yaml` | New (D23 C). Replaces the hand-written `scripts/hooks/pre-commit`: the pre-commit framework runs gitleaks, `ruff check --fix`, `ruff format` and six hygiene checks (merge markers, YAML, TOML, end of file, trailing spaces, large files) before every commit. Tested here: it blocked a token-shaped string with the value redacted and fixed a messy Python file |
| `.github/workflows/ci.yml` | New. Both jobs on Windows (D24 B): ruff format check, ruff lint and pyright in one; pytest with coverage, Qt headless, in the other. `secret-scan.yml` stays on Ubuntu because the gitleaks action is only documented there; it scans text and runs no app code. Python 3.14, `uv sync --locked`. Switched on by #4 with both actions pinned to commit SHAs (`actions/checkout` v7.0.1, `astral-sh/setup-uv` v10.3.0) |
| `pyproject.toml` | New. Package `fairshuffle` 0.1.0, MIT, Python 3.14+, PySide6-Essentials, dev group (ruff, pyright with bundled Node, pytest, pytest-qt, pytest-cov, pre-commit), ruff rules including the bandit `S` security set |
| `README.md` (starter kit) | File table updated with these changes |

`secret-scan.yml`, the agents, the skills, the templates and `.env.example` are unchanged.

---

## 7. Facts this roadmap relies on

Spotify Web API (Rule 4): everything in PROJECT_PLAN section 2.2 was re-verified on 2026-10-08 with no changes since 2026-09-24 (`setup/stage-a-recheck-2026-10.md` in the project folder). On 2026-10-09 a search found no changelog newer than July 2026, and two more reference pages were read:

- `GET /me/playlists`: limit up to 50 (default 20), scope `playlist-read-private`, returns owned and followed playlists; each has `owner.id`, `collaborative`, `snapshot_id` and the count in `items.total`; `tracks` is marked deprecated. Used in P3-02.
- `GET /me`: returns `id`, `display_name` and a new `account_id`; `email`, `country`, `product`, `explicit_content` and `followers` are marked deprecated. Scope question noted in section 3.3 for P2-02.

Tooling (checked 2026-10-09 on PyPI, GitHub and python.org): versions in section 3.6; Python 3.14 is the newest bug-fix branch and 3.15 is not final; `astral-sh/setup-uv` latest is v10.2.0 (v10 disabled caching on release and `pull_request_target` events); `actions/checkout` latest is v7.0.1. pytest-qt 4.5.0 predates Python 3.14 but installed cleanly on it. A full Qt test run in this Linux container failed on a missing system graphics library (libEGL), which is one reason the recommended CI runs Qt tests on Windows (D24); P1-03 confirms on Windows.
