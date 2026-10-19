# Project Plan: Playlist Shuffler (working name)

Owner: Derek Burns. Plan researched and written September 24, 2026.
Audience: Claude Code (executes the plan) and Derek (decides everything).

## Contents

0. How to run this plan
1. Goal and scope
2. Research findings
3. How the app will be made (architecture)
4. Claude Code toolkit: agents, skills, connectors, plugins, hooks
5. Secret safety plan
6. GitHub setup and workflow
7. Decisions overview
8. Roadmap (Stages A to D, Phases 0 to 8)
9. Feature backlog
10. Risks and mitigations
11. Resume angle
12. Sources

---

## 0. How to run this plan

Work through four stages in order. Do not skip ahead.

| Stage | What happens | Output | Code written? |
|-------|--------------|--------|---------------|
| A. Research check | Re-verify section 2 against current official sources | Stage A report (one screen) | No |
| B. Decisions | Teach the Claude Code basics, then present Decision Cards D1 to D8 one at a time | Answers logged in DECISIONS.md | No |
| C. Final roadmap | Turn Derek's answers into a concrete, stack-specific roadmap, milestones and issue list | Updated section 8 for Derek's approval | No |
| D. Build | Phase 0 setup, then Phases 1 to 8 | Working app, all on GitHub | Yes |

Rules that apply everywhere are in `CLAUDE.md`. The short version: Derek decides, secrets never leave his PC, every change goes through a pull request.

---

## 1. Goal and scope

**Problem.** Spotify's shuffle is not a plain random shuffle. Listeners with large playlists report hearing the same songs often and some songs rarely. The reference tool (stevenaleong.com/tools/spotifyplaylistrandomizer) sidesteps this by permanently rewriting a playlist into a random order, so you can play it from track 1 with shuffle off.

**What we are building.** The same idea as a Windows desktop app that sits in the system tray:

1. Sign in to Spotify once (secure, no password stored by the app).
2. Click the tray icon, pick a playlist.
3. The app writes a truly random order into that playlist.
4. Play it from the top in Spotify with shuffle off and sort set to "Custom order".

**Success criteria for v1.0**

- Installs or runs on Windows 11 from a GitHub Release download.
- Tray icon appears in the hidden icons flyout; menu works with mouse and keyboard.
- Shuffles a 500-song playlist reliably, with a progress indicator, without losing or duplicating songs.
- Survives: expired tokens, rate limiting, network drops, playlists edited during a shuffle.
- Zero secrets in the Git history. CI green. README good enough for a recruiter to understand the project in 60 seconds.

**Out of scope (unless Derek adds them from the backlog):** macOS or Linux builds, a public multi-user service, playback control, Liked Songs (not a playlist, cannot be reordered through the API).

---

## 2. Research findings

Stage A re-checks every row. Anything that changed goes in the Stage A report and into the `spotify-api-notes` skill.

### 2.1 How the reference tool works

- Signs in through Spotify OAuth in the browser.
- Reorders tracks **in place** inside the existing playlist. No new playlist is created.
- Changes are permanent and cannot be undone by the tool; it tells users to make a backup copy first.
- Cannot shuffle Liked Songs (API restriction). Workaround: copy Liked Songs to a normal playlist first.
- Can fail when too many requests hit Spotify at once (rate limiting).
- Afterwards the user plays from the first track with shuffle off and sort set to Custom order.

Our improvements to aim for: a backup and undo, progress and cancel, graceful rate-limit handling and no browser tab needed after the first sign-in.

### 2.2 Spotify Web API facts that shape the design

| # | Fact (verified Sept 24, 2026) | What it means for us |
|---|-------------------------------|----------------------|
| 1 | Development mode apps require the app owner to have Spotify Premium (new apps from Feb 11, 2026; existing apps from Mar 9, 2026). | Derek needs Premium to own the app. |
| 2 | Development mode allows up to 5 authorized users per app. Since July 2026 a developer can create up to 25 Client IDs, but quotas are counted per developer account. Individuals cannot get extended quota. | Personal tool plus up to 4 friends. Anyone else follows a "bring your own Client ID" guide in the README. |
| 3 | Playlist endpoints were renamed from `/playlists/{id}/tracks` to `/playlists/{id}/items` (GET, POST, PUT, DELETE). In responses the `tracks` field became `items` and `tracks.track` became `items.item`. Old paths return 403 for dev mode apps. | Use `/items` only. Many tutorials and older libraries are now wrong. |
| 4 | `GET /playlists/{id}/items`: max 50 per page (default 20). Only works for playlists the user owns or collaborates on; others return 403. | Page through in 50s. Only list owned or collaborative playlists. |
| 5 | `PUT /playlists/{id}/items` does either reorder (`range_start`, `insert_before`, `range_length`, `snapshot_id`) or replace (`uris`, max 100 per request). They cannot be combined in one request. | Two shuffle strategies are possible (see 2.4 and D12). |
| 6 | `POST /users/{id}/playlists` became `POST /me/playlists`. `GET /users/{id}/playlists` became `GET /me/playlists`. `GET /users/{id}` removed. | Use `/me` paths everywhere. |
| 7 | Several fields were removed (for example track `popularity`, user `email`, `country`, `product`). | Do not build features on removed fields. |
| 8 | Authorization Code with PKCE is Spotify's recommended flow for apps that cannot keep a secret. No client secret is used. | Nothing secret ships in the app. The Client ID is still kept out of Git out of habit. |
| 9 | Redirect URIs: `localhost` is not allowed. Use `http://127.0.0.1:PORT` or `http://[::1]:PORT`. Plain HTTP is only allowed for loopback. A loopback URI can be registered without a port and the port supplied at runtime. | The app runs a one-shot local listener on 127.0.0.1 to catch the sign-in callback. |
| 10 | Refresh tokens expire 6 months after the original authorization (new apps from June 18, 2026; existing apps from July 20, 2026). Refreshing does not extend this. Expired tokens return `400 invalid_grant`; Spotify says do not retry, send the user to sign in again. | Build a clean "please sign in again" path from day one. |
| 11 | Rate limits use a rolling 30-second window. A 429 response includes `Retry-After`. Since July 2026 quota overruns return 429 with `"reason": "QUOTA_EXCEEDED"`. Numeric limits are not published. | Pace requests, honour `Retry-After`, count calls and show progress. |
| 12 | Branding: an app name must not include "Spotify" or sound like it; "for Spotify" wording is acceptable. Spotify content shown in the app must be attributed per the design guidelines. | App name decision D3. Original icon, not the Spotify logo. |
| 13 | Libraries: `spotipy` 2.26.0 (Mar 3, 2026) moved to `/items`. `SpotifyAPI.Web` 7.3.0 (Feb 15, 2026) implemented the Feb 2026 changes and 7.4.2 (Mar 4, 2026) fixed playlist replace. Rust's `rspotify`: **corrected in Stage A re-check (Sept 24, 2026)** — 0.16.0 added `/items` support and the Feb 2026 removals, and 0.16.1 is the current release (Apr 25, 2026). The earlier "still on 0.14.0" note was wrong. | Library choice D9. A small hand-written client is also realistic. For Tauri, `rspotify` 0.16.1 is now a real option, so an own client is a choice rather than a requirement. |
| 14 | Liked Songs is not a playlist, so it cannot be reordered. `GET /me/tracks` (read Liked Songs, max 50 per page, scope `user-library-read`) still exists (Stage A). The Feb 2026 changelog contradicts itself on this endpoint, so re-check before building on it. | Backlog idea is feasible: copy Liked Songs into a playlist, then shuffle. Needs one extra scope. |

Verified in Stage A: the Web API cannot add local files to a playlist, but it can reorder and remove them (Spotify "Playlists" concept page). So reorder (strategy A) keeps local files and replace or copy (B, C) loses them. Episodes are normal `spotify:episode:` URIs and survive all three strategies.

### 2.2.1 Additional development mode removals (found in the Sept 24, 2026 re-check)

None of these block the shuffle feature, but they rule out some obvious workarounds and they change the call budget.

| # | Fact | What it means for us |
|---|------|----------------------|
| 15 | Batch fetch endpoints are gone for dev mode apps: `GET /tracks`, `/albums`, `/artists`, `/episodes`, `/shows`, `/audiobooks`, `/chapters`. Fetch one at a time instead. | Directly contradicts the "use batch APIs" advice on Spotify's own rate limits page, which was written for extended quota apps. If we ever need per-track detail beyond what `/playlists/{id}/items` already returns, it costs one call per track. Avoid designing any feature that needs it. |
| 16 | `GET /search` maximum `limit` dropped from 50 to 10 (default 20 to 5). | Only matters if we add search to the playlist picker (D11). Page with `offset`. |
| 17 | `DELETE /playlists/{id}/items` renamed its body parameter from `tracks` to `items`. | Only relevant if we add a remove feature. |
| 18 | Track and album `external_ids` were removed in Feb 2026 then reverted in Mar 2026, so they exist again. Track `popularity` and user `email`, `country`, `product` are still gone. | Row 7 stands, with `external_ids` as the exception. |
| 19 | All Feb 2026 restrictions apply to **development mode only**. Extended quota apps keep every old endpoint, field and behaviour. | This is why the reference tool still calls `GET /users/{id}` and `GET /users/{id}/playlists`, which we cannot use. We cannot copy its request pattern directly. |
| 20 | Existing apps are grandfathered on the Client ID and user limits. New apps are not. | Derek's app will be new, so 25 Client IDs and 5 users apply. |

### 2.3 Why a "true" shuffle

The app uses the Fisher-Yates algorithm, which gives every possible order exactly the same probability, driven by the operating system's cryptographically secure random generator (so even very long playlists can land in any possible order). This is simple, provable and easy to unit test, which is a good resume talking point.

### 2.4 Shuffle strategies (feeds Decision D12)

For a playlist of N songs:

| Strategy | API calls (N = 500) | Keeps "date added" and "added by" | Keeps local files | Speed | Main risk |
|----------|---------------------|-----------------------------------|-------------------|-------|-----------|
| A. Reorder in place (move one item at a time) | up to 499 | Yes | Yes | Slow (minutes on big lists) | Rate limiting; long run can be interrupted |
| B. Replace in place (write the new order in chunks of 100) | 5 | No, all reset | No (confirmed) | Fast (seconds) | A failure halfway leaves a partial playlist (mitigated by backup) |
| C. Write a shuffled copy to a separate playlist | 6 | No (in the copy) | No (confirmed) | Fast | Extra playlist in the library; original untouched |

Reorder plan for A: build the target order, then for each position i from the top, move the song that belongs at i from its current position to i with `range_start = current`, `insert_before = i`, `range_length = 1`, passing the latest `snapshot_id` each time. Skip moves where the song is already in place. The plan is computed and tested offline before any API call.

### 2.5 Windows tray behaviour

On Windows 11, new tray icons land in the hidden icons flyout (the `^` arrow) by default, which is exactly where Derek wants it. The user can pin it to the visible taskbar in Settings > Personalization > Taskbar > Other system tray icons. Apps cannot force themselves onto the visible taskbar, and should not try.

---

## 3. How the app will be made (architecture)

> Stage C (approved 2026-10-09): the Python architecture with real module names is in `ROADMAP.md` section 3 and replaces this section.

Language-neutral. Stage C maps each box to real modules once D1 is decided.

```
            Windows notification area (hidden icons flyout)
                              |
                 +------------v-------------+
                 |  Tray shell              |
                 |  icon, menu, tooltip,    |
                 |  notifications, window   |
                 +--+----------+---------+--+
                    |          |         |
       +------------v--+  +----v------+  +v-------------------+
       | Auth          |  | Shuffle   |  | Settings, backups, |
       | PKCE sign-in, |  | engine    |  | logs (%APPDATA%,   |
       | loopback      |  | (pure     |  | %LOCALAPPDATA%)    |
       | listener,     |  | functions,|  +--------------------+
       | token refresh |  | no I/O)   |
       +-------+-------+  +----+------+
               |               |
       +-------v---------------v------+
       | Spotify API client           |
       | HTTPS, paging, 429 backoff,  |
       | snapshot_id, error mapping   |
       +---------------+--------------+
                       |
        accounts.spotify.com   api.spotify.com

  Refresh token -> Windows Credential Manager (never a file in the repo)
```

### 3.1 Sign-in flow (OAuth 2.0 Authorization Code with PKCE)

1. User clicks "Sign in" in the tray menu.
2. App creates a random `code_verifier` (43 to 128 characters), its SHA-256 `code_challenge` (base64url) and a random `state`.
3. App starts a one-shot HTTP listener bound to 127.0.0.1 only (never 0.0.0.0) on the registered port.
4. App opens the default browser at `accounts.spotify.com/authorize` with `client_id`, `response_type=code`, `redirect_uri`, `code_challenge_method=S256`, `code_challenge`, `state` and the scopes.
5. User approves. Spotify redirects the browser to `http://127.0.0.1:PORT/callback?code=...&state=...`. The listener checks `state`, shows "You can close this tab" and shuts down.
6. App exchanges `code` and `code_verifier` at `accounts.spotify.com/api/token` for an access token (about 1 hour) and a refresh token.
7. Refresh token goes to Windows Credential Manager. Access token stays in memory only.
8. On 401: refresh. On `400 invalid_grant`: delete the stored token and ask the user to sign in again.

**Scopes (least privilege):** `playlist-read-private`, `playlist-read-collaborative`, `playlist-modify-private`, `playlist-modify-public`. Confirm in Stage A that nothing else is needed.

### 3.2 Shuffle flow

1. User picks a playlist (tray submenu or picker window, decided in D11).
2. App fetches all items in pages of 50 and records the playlist's `snapshot_id`.
3. App saves a backup of the current order to `%APPDATA%\<AppName>\backups\` (D13).
4. Shuffle engine produces a random order and a plan for the chosen strategy (D12).
5. App applies the plan with pacing, honours `Retry-After`, shows progress and allows cancel.
6. App re-reads the playlist to verify nothing was lost or duplicated.
7. Notification: "Shuffled 342 songs. Play from track 1 with Spotify shuffle off and sort set to Custom order."

### 3.3 Where data lives

| Data | Location | In Git? |
|------|----------|---------|
| Spotify Client ID (development) | `.env` in the project folder | Never (gitignored, blocked from Claude) |
| Refresh token | Windows Credential Manager | Never |
| Access token | Memory only | Never |
| Settings (no secrets) | `%APPDATA%\<AppName>\settings.json` | No |
| Playlist backups | `%APPDATA%\<AppName>\backups\` | No |
| Logs (tokens redacted) | `%LOCALAPPDATA%\<AppName>\logs\` | No |

How the Client ID gets into a packaged release build is decided in Phase 8 (D17).

---

## 4. Claude Code toolkit: agents, skills, connectors, plugins, hooks

Beginner explanations are in `CLAUDE_CODE_PRIMER.md`. Teach them to Derek at the start of Stage B, before D7. Everything below is **proposed**. Derek approves each item in D7, then Claude installs it in Phase 0 and demonstrates it once.

### 4.1 The team

The main Claude Code session is the tech lead: it plans, writes the app code, coordinates the specialists and talks to Derek. Specialists (subagents) take focused jobs and report back, which keeps the main conversation short and on topic.

| Agent (file in starter-kit) | Its job here | Tools it gets | Used in |
|-----------------------------|--------------|---------------|---------|
| `spotify-api-researcher` | Fact-checks Spotify endpoints, scopes, limits and changelog before API code is written | Read-only plus web | Stage A, Phases 2 to 4, any API change |
| `security-reviewer` | Reviews diffs for secrets, token handling, logging and loopback listener safety; returns PASS or FAIL | Read-only plus git commands | Every pull request |
| `test-engineer` | Writes and runs tests with mocked Spotify responses; failing test first for every bug | Read, write, run | Phases 1 to 6 |
| `ui-designer` | Mockup options, Windows 11 look, icon, accessibility | Read, write, web | Phases 3 and 7 |
| `docs-writer` (optional) | README, CHANGELOG, architecture notes, release notes, resume bullets | Read, write | End of each phase, Phase 8 |

Subagents use `model: sonnet` to save plan usage. Derek can change this.

### 4.2 Skills (project playbooks)

| Skill | What it teaches Claude | How it runs |
|-------|------------------------|-------------|
| `decision-card` | The exact card format and the rule to stop and wait | Automatically whenever a choice comes up, or `/decision-card` |
| `spotify-api-notes` | The verified, dated API facts from section 2 | Automatically before any Spotify code, or `/spotify-api-notes` |
| `ship-change` | The Git workflow: tests, security review, commit, push, PR | When a task is done, or `/ship-change` |
| `phase-report` | End-of-phase report plus the "What's next?" card | End of each phase or session, or `/phase-report` |

### 4.3 MCP connectors

| Connector | What it lets Claude do | Setup and safety | Recommendation |
|-----------|------------------------|------------------|----------------|
| GitHub MCP (via the official `github` plugin, or `claude mcp add`) | Create and update issues, milestones, pull requests and reviews through GitHub's API | Needs a fine-grained personal access token limited to this one repo. Token lives in an environment variable, never in `.mcp.json` | Recommended (Derek wants to learn connectors) |
| Context7 | Pulls current documentation for libraries (spotipy, PySide6, Tauri and so on) so code matches today's versions | Works without a key at low volume; key optional, stored as `CONTEXT7_API_KEY` env var. Install options (Stage A): `context7` plugin in the official marketplace, Context7's own plugin marketplace, or `npx ctx7 setup --claude` (needs Node.js) | Recommended |
| Spotify MCP servers | Would let Claude control Derek's Spotify | Third-party servers would hold his Spotify tokens; not needed to build this app | Not recommended |
| Browser automation (Playwright) | Drives websites | This is a desktop app, not a website | Not needed |

The GitHub CLI (`gh`) is not a connector but does most of the same GitHub work from the command line. Recommended regardless, because it handles sign-in (`gh auth login`) cleanly.

### 4.4 Plugins (official Anthropic marketplace)

Install with `/plugin` (Discover tab) or `/plugin install <name>@claude-plugins-official`. All names below confirmed in the official marketplace in Stage A (Sept 24, 2026). The marketplace also now has `claude-security` and `code-review`, which overlap with `security-guidance`, `pr-review-toolkit` and our `security-reviewer` agent.

| Plugin | What it adds | Recommendation |
|--------|--------------|----------------|
| Code intelligence for the chosen language: `pyright-lsp` (Python), `csharp-lsp` (C#), `rust-analyzer-lsp` plus `typescript-lsp` (Tauri) | Claude sees type errors right after each edit | Recommended after D1 (needs the language server binary installed) |
| `security-guidance` | Reviews each change Claude makes for common vulnerabilities | Recommended |
| `github` | Bundles the GitHub MCP connector | Recommended if Derek picks the GitHub connector |
| `explanatory-output-style` or `learning-output-style` | Teaching mode: Claude explains its choices, or has Derek write small pieces himself | Decided in D8 |
| `commit-commands` | Ready-made commit, push and PR skills | Optional; overlaps with our `ship-change` skill, pick one |
| `pr-review-toolkit` | Extra review agents for PRs | Optional; useful later |

### 4.5 Hooks and permissions

| Guardrail | Type | What it does |
|-----------|------|--------------|
| `scripts/hooks/pre-commit` (gitleaks) | Git hook | Blocks any commit, by Derek or Claude, that contains something that looks like a secret |
| `.github/workflows/secret-scan.yml` | CI | Runs gitleaks on every pull request and push to `main` |
| `.claude/settings.json` deny rules | Claude Code permissions | Claude cannot read or edit `.env` or `secrets/`, cannot force-push or hard reset |
| `.claude/settings.json` ask rules | Claude Code permissions | Claude must ask before push, merge, repo create, tag or release, even in auto mode |
| Formatter hook (added after D1) | Claude Code `PostToolUse` hook | Auto-formats files after every edit (for example `ruff format`, `dotnet format` or `cargo fmt` plus Prettier) |

---

## 5. Secret safety plan

Layered, like defence in depth on a network: no single layer has to be perfect.

| Layer | Protection | When it acts |
|-------|------------|--------------|
| Design | PKCE means no client secret exists at all | Always |
| Storage | Tokens only in Windows Credential Manager; access token only in memory | Runtime |
| Git ignore | `.gitignore` (committed first, before any code) excludes `.env`, token caches, backups, logs, build output | Every `git add` |
| Claude permissions | `.env` and `secrets/` denied to Claude's file tools | Every Claude action |
| Pre-commit hook | gitleaks scans staged changes and blocks the commit | Every commit |
| Review | `security-reviewer` agent checks every PR diff | Every PR |
| CI | gitleaks GitHub Action on PRs and `main` | Every push |
| GitHub | Push protection for users blocks known secret formats pushed to public repos (on by default); secret scanning alerts on public repos | Every push |
| Hygiene | Fake values in tests, redacted logs, noreply commit email, no personal paths | Always |
| Incident plan | Stop, tell Derek, rotate first, clean history only with approval | If anything leaks |

Test credentials rule: automated tests never use real accounts or tokens and never call Spotify. Manual testing uses Derek's own account through the real sign-in flow, on a throwaway test playlist first.

---

## 6. GitHub setup and workflow

### 6.1 One-time setup (Claude walks Derek through it in Phase 0)

1. Sign in to GitHub. Turn on two-factor authentication.
2. Optional: apply for the GitHub Student Developer Pack with the Carleton or Algonquin email. It includes GitHub Pro while a student, which unlocks branch protection on private repos.
3. Email privacy: Settings > Emails > turn on "Keep my email addresses private" and "Block command line pushes that expose my email". Copy the `...@users.noreply.github.com` address.
4. Install tools (Claude asks before each): Git for Windows, GitHub CLI (`winget install --id GitHub.cli`), gitleaks and the language toolchain from D1.
5. `gh auth login` in a terminal. Browser sign-in; no password ever goes in the chat.
6. Git identity: `git config --global user.name "Derek Burns"`, `git config --global user.email "<noreply address>"`, `git config --global init.defaultBranch main`.
7. `git init`, activate the versioned hooks with `git config core.hooksPath scripts/hooks`, first commit: `chore: initial project scaffolding and planning docs`.
8. Create the GitHub repo with the name and visibility from D3 and D4, then push.
9. Repo settings: protect `main` (require PR, require status checks, block force pushes), enable secret scanning and Dependabot alerts where the plan allows, turn on Issues, create a Projects board called "Roadmap".
10. Labels (`type:feature`, `type:bug`, `type:docs`, `type:chore`, `priority:high/med/low`) and one milestone per phase. Issues from the Stage C list.

### 6.2 Repository layout (finalized in Stage C)

```
/
  CLAUDE.md               standing rules for Claude Code
  README.md               what it is, screenshots, how to install and use
  LICENSE                 from D5
  CHANGELOG.md            per release
  .gitignore
  .env.example            placeholders only
  .claude/
    settings.json         permissions and hooks (shared)
    agents/               approved subagents
    skills/               approved skills
  .github/
    workflows/            CI: tests, lint, secret scan, release build
    ISSUE_TEMPLATE/
    pull_request_template.md
  scripts/hooks/pre-commit
  docs/
    planning/             this plan, decisions, primer
    architecture.md
    screenshots/
  src/                    app code (layout depends on D1)
  tests/
  assets/                 icons
```

### 6.3 Everyday flow (GitHub Flow, like most product teams)

```
Issue #12 "PKCE sign-in"
  -> branch feat/12-pkce-sign-in
  -> small commits (feat:, test:, fix:)
  -> tests pass locally, security-reviewer PASS
  -> push (Derek approves) -> pull request "Closes #12"
  -> CI green -> Derek reviews and approves merge
  -> squash merge -> branch deleted -> milestone progress updates
```

### 6.4 Versions

| Tag | Meaning |
|-----|---------|
| v0.1.0 | Creation: tray app skeleton |
| v0.2.0 | Goal 1: Spotify sign-in |
| v0.3.0 | Goal 2: playlists listed |
| v0.4.0 | Goal 3: shuffle engine |
| v0.5.0 | Prototype (GitHub pre-release) |
| v0.6.x | Bug fixes and hardening |
| v0.9.0 | Visual polish (release candidate) |
| v1.0.0 | Final project |

---

## 7. Decisions overview

Full cards with pros and cons are in `DECISIONS.md`. Present each at the time shown, one at a time.

| ID | Decision | When |
|----|----------|------|
| D1 | Language and framework | Stage B |
| D2 | UI toolkit within that stack | Stage B, right after D1 |
| D3 | App and repo name | Stage B |
| D4 | Repo visibility | Stage B |
| D5 | License | Stage B |
| D6 | How "workplace" the GitHub process should be | Stage B |
| D7 | Which agents, skills, connectors and plugins to install | Stage B (after the primer walkthrough) |
| D8 | Teaching style (output style plugin) | Stage B |
| D9 | Spotify library or own small HTTP client | Phase 2 |
| D10 | Token storage method | Phase 2 |
| D11 | Tray UI shape | Phase 3 |
| D12 | Shuffle strategy | Phase 4 |
| D13 | Backup and undo | Phase 4 |
| D14 | Which backlog features to add | End of Phase 5 |
| D15 | Distribution format | Phase 8 |
| D16 | Code signing | Phase 8 |
| D17 | Client ID in release builds (own ID per user or yours built in) | Phase 8 |
| Any time | "What's next?" when more than one next step is valid | Between tasks and phases |

---

## 8. Roadmap

Each phase lists: goal, main tasks, agents and skills used, decisions asked, definition of done (DoD) and Git milestone. When a phase ends, run `phase-report` and ask Derek what's next. The default order below is a suggestion; if Derek prefers a different order (for example UI before shuffle), follow his choice.

### Stage A: Research check (no code)

- Do this with Claude's built-in tools; the custom agents are not installed yet.
- Re-verify every row in section 2.2 and 2.4 against developer.spotify.com (reference pages, changelog pages under `references/changes/`, developer blog). Look for changelog entries after July 2026.
- Confirm: the stevenaleong tool still behaves as described; current versions of spotipy, SpotifyAPI.Web and rspotify; Claude Code plugin names and install commands; current gitleaks command syntax and GitHub Action versions; the Dispatch and Claude Code features used in this plan.
- Output: a one-screen Stage A report with three headings: Confirmed, Changed, New risks. Update this plan and the `spotify-api-notes` starter skill where facts changed.

### Stage B: Teach, then decide (no code)

1. Five-minute walkthrough of `CLAUDE_CODE_PRIMER.md`: what CLAUDE.md, skills, subagents, MCP connectors, hooks, plugins and permissions are, using this project's examples. Check Derek is comfortable before moving on.
2. Decision Cards D1 to D8, one per message. Log each answer.
3. If an answer changes other parts of the plan (for example D1 changes the .gitignore and CI), say what will change.

### Stage C: Final roadmap (no code)

- Rewrite section 3 with real module names for the chosen stack.
- Turn Phases 0 to 8 into a numbered issue list per milestone (title, one-line description, acceptance criteria).
- Tailor the starter-kit `.gitignore`, formatter hook and CI workflow to the stack.
- Show Derek the result; create nothing on GitHub until Phase 0.

> Stage C (approved 2026-10-09): `ROADMAP.md` sections 4 and 5 hold the tailored Phase 0 checklist and the issue list for Phases 1 to 8; they replace the task lists below where they differ.

### Stage D, Phase 0: Setup (part of Creation)

- **Goal:** tools installed, GitHub ready, safety nets on, the Claude Code team in place.
- **Tasks:**
  1. Check what is installed (git, gh, gitleaks, language toolchain). Ask before each install.
  2. GitHub one-time setup (section 6.1 steps 1 to 6).
  3. Copy approved starter-kit files into place (`.gitignore`, `.env.example`, `.claude/`, `.github/`, `scripts/hooks/`). Show Derek each file briefly and explain it.
  4. `git init`, hooks path, first commit, create the GitHub repo (with approval), push.
  5. Install approved plugins and MCP connectors one at a time. After each: explain what it does and run one harmless demo (GitHub MCP lists the repo's issues; Context7 fetches docs for the chosen library).
  6. Demo each agent once (for example `security-reviewer` reviews the first commit) and each skill once.
  7. Repo settings, labels, milestones, issues from Stage C, Projects board.
- **Decisions:** none new (all from Stage B), but ask before every install and every GitHub change.
- **DoD:** repo live, `main` protected, secret scan workflow green, Derek can describe each tool in one sentence.
- **Milestone:** part of v0.1.0.

### Phase 1: Creation (v0.1.0)

- **Goal:** an app that starts, shows a tray icon in the hidden icons flyout and quits cleanly.
- **Tasks:** project scaffold for the chosen stack; tray icon with tooltip and a menu (About, Quit); single-instance guard; logging setup with a redaction filter; test framework plus the first tests; CI workflow for lint and tests on PRs; README skeleton.
- **Agents and skills:** `test-engineer`, `security-reviewer`, `ship-change`.
- **DoD:** Derek runs it from source, sees the icon under `^`, Quit works; CI green on the PR.

### Phase 2: Goal 1, Connect to Spotify (v0.2.0)

- **Goal:** sign in and sign out securely.
- **Tasks:**
  1. Walk Derek through creating the Spotify app at developer.spotify.com/dashboard: name without "Spotify", Redirect URI `http://127.0.0.1:<port>/callback`, Web API checked, his account added under User Management if needed. He copies the Client ID into `.env` himself.
  2. Decisions D9 (library or own client) and D10 (token storage).
  3. Implement PKCE sign-in, loopback listener, token exchange, refresh, `invalid_grant` handling, sign out.
  4. Tray shows "Signed in as <display name>".
- **Agents and skills:** `spotify-api-researcher` first, then `test-engineer`, then `security-reviewer` (mandatory, auth code).
- **DoD:** sign in, restart the app, still signed in without a browser; sign out removes the token from Credential Manager; tests cover state mismatch and `invalid_grant`.

### Phase 3: Goal 2, See your playlists (v0.3.0)

- **Goal:** list the playlists the app can shuffle.
- **Tasks:** `GET /me/playlists` with paging; keep only playlists Derek owns or collaborates on; item counts; refresh; cache keyed by `snapshot_id`; decision D11 (tray submenu, picker window or both) with `ui-designer` mockups; handle 0 playlists and very many playlists.
- **DoD:** Derek's real playlists appear correctly; read-only so nothing can be damaged yet.

### Phase 4: Goal 3, True shuffle engine (v0.4.0)

- **Goal:** shuffle a playlist correctly and safely.
- **Tasks:**
  1. Decisions D12 (strategy) and D13 (backup and undo).
  2. Pure shuffle engine: Fisher-Yates with a secure random source; plan builder for the chosen strategy.
  3. Tests: output is a true permutation (nothing lost or duplicated, including duplicate songs, local files and episodes); statistical uniformity check on small lists; plan replay against a simulated playlist; call count.
  4. Apply the plan with pacing, `Retry-After` handling, progress and cancel; verify afterwards.
  5. Derek creates a throwaway playlist (about 30 songs) called "Shuffle Test". First live run happens only on that playlist, and only after Derek says go. Ask again before the first run on a real playlist.
- **Agents and skills:** `spotify-api-researcher`, `test-engineer`, `security-reviewer`.
- **DoD:** 10 shuffles of the test playlist, verified each time; a real playlist shuffled at Derek's request.

### Phase 5: Prototype (v0.5.0, GitHub pre-release)

- **Goal:** end-to-end app Derek uses for a few days.
- **Tasks:** wire everything together; completion notification with the "play from track 1, shuffle off" tip; package a runnable build for the chosen stack; publish as a pre-release; Derek logs issues from real use (Claude helps write them); decision D14 (backlog picks).
- **DoD:** Derek uses it from the tray without a terminal.

### Phase 6: Bug fixes and hardening (v0.6.x)

- **Goal:** reliable under bad conditions.
- **Tasks:** triage issues with Derek (priority card); for each bug write a failing test first, then fix; edge cases: empty playlist, 1 song, 1,000+ songs, duplicate songs, playlist edited mid-shuffle (snapshot mismatch), network drop mid-shuffle, 429 storms, expired token, Premium lapsed, PC sleeping mid-run; clear error messages; log review for leaks.
- **DoD:** no open high-priority bugs; all edge cases have tests.

### Phase 7: Visual polish (v0.9.0)

- **Goal:** looks and feels like a native Windows 11 app.
- **Tasks:** `ui-designer` presents 2 or 3 mockup options per screen as Decision Cards; original tray icon (light and dark variants); follow Windows light or dark theme; tidy menu wording; settings window; progress UI; accessibility check (keyboard, contrast, screen reader names); screenshots and a short demo GIF for the README.
- **DoD:** Derek approves each screen; screenshots committed.

### Phase 8: Final project (v1.0.0)

- **Goal:** a finished, downloadable, portfolio-ready project.
- **Tasks:** decisions D15 (distribution), D16 (signing) and D17 (Client ID in release builds); GitHub Actions release build triggered by a version tag; final README (demo GIF, features, how it works, architecture diagram, "bring your own Client ID" guide, privacy statement: data only goes between your PC and Spotify); CHANGELOG; LICENSE; repo description and topics; pin the repo on Derek's profile; `docs-writer` drafts resume bullets and interview talking points for Derek to edit.
- **DoD:** v1.0.0 release published; a fresh Windows user can install and use it by following the README.

---

## 9. Feature backlog (Derek picks in D14)

| Idea | Effort | Notes |
|------|--------|-------|
| Undo last shuffle (restore from backup) | Medium | Big improvement over the reference tool |
| Shuffle several playlists at once | Low | |
| Scheduled reshuffle (for example every Monday) | Medium | App must be running |
| Start with Windows | Low | Off by default |
| Global hotkey to shuffle the last playlist | Medium | |
| "Shuffle and open in Spotify" | Low | Opens the playlist in the Spotify app; no extra API scope |
| Copy Liked Songs into a playlist, then shuffle | Medium | Verify the endpoint in Stage A |
| Artist spacing mode (avoid the same artist back to back) | Medium | Optional mode; plain random stays the default |
| Shuffle history | Low | Local only |
| Update checker using GitHub Releases | Medium | |

---

## 10. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Spotify changes the API again | `spotify-api-researcher` plus dated notes; all API calls isolated in one client module |
| Rate limits on big playlists | Pacing, `Retry-After`, progress and cancel, faster strategy available (D12) |
| Interrupted shuffle damages a playlist | Backup before every run, resume or restore, verify after |
| Refresh token expires every 6 months | Clean "sign in again" prompt |
| Premium lapses | App shows a clear message; documented in README |
| Unsigned app triggers SmartScreen or antivirus warnings | D16; README explains; build from source option |
| Secret leak | Section 5 layers |
| Scope creep | Backlog plus D14 |
| Claude plan usage limits | Small agent team on `sonnet`, one phase per session, `/clear` between phases |

---

## 11. Resume angle

Points this project can back up, which also fit a networking degree:

- OAuth 2.0 Authorization Code with PKCE, loopback redirect bound to 127.0.0.1, HTTPS REST API integration.
- Rate limiting and resilience: HTTP 429, `Retry-After`, backoff, idempotent verification.
- Algorithms: unbiased Fisher-Yates shuffle with a cryptographically secure random source, with statistical tests.
- Security: least-privilege scopes, OS credential store, secret scanning in pre-commit and CI, no secrets in history.
- Professional workflow: issues, milestones, feature branches, PR reviews, CI, SemVer releases, changelog.
- AI-assisted engineering: directed a Claude Code agent team (research, security review, testing, UI) with human approval gates.

The `docs-writer` agent drafts bullets in Phase 8; Derek edits them to his own resume rules.

---

## 12. Sources

- Reference tool: https://stevenaleong.com/tools/spotifyplaylistrandomizer
- Feb 2026 migration guide: https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide
- Dev access update (Feb 6, 2026): https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security
- Changelogs: https://developer.spotify.com/documentation/web-api/references/changes/february-2026 , .../march-2026 , .../may-2026 , .../july-2026
- Refresh token expiration (June 18, 2026): https://developer.spotify.com/blog/2026-06-18-refresh-token-expiration
- Update playlist items: https://developer.spotify.com/documentation/web-api/reference/reorder-or-replace-playlists-items
- Get playlist items: https://developer.spotify.com/documentation/web-api/reference/get-playlists-items
- PKCE flow: https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow
- Redirect URIs: https://developer.spotify.com/documentation/web-api/concepts/redirect_uri
- Rate limits: https://developer.spotify.com/documentation/web-api/concepts/rate-limits
- Design and branding: https://developer.spotify.com/documentation/design
- Old endpoints returning 403: https://github.com/music-assistant/support/issues/5114
- spotipy releases: https://github.com/spotipy-dev/spotipy/releases
- SpotifyAPI-NET releases: https://github.com/johnnycrazy/spotifyapi-net/releases
- rspotify tracking issue: https://github.com/ramsayleung/rspotify/issues/550
- Tauri 2 system tray: https://v2.tauri.app/learn/system-tray/
- Claude Code subagents: https://code.claude.com/docs/en/sub-agents
- Claude Code skills: https://code.claude.com/docs/en/skills
- Claude Code MCP: https://code.claude.com/docs/en/mcp
- Claude Code hooks: https://code.claude.com/docs/en/hooks-guide
- Claude Code permissions and settings: https://code.claude.com/docs/en/permissions , https://code.claude.com/docs/en/settings
- Claude Code plugins: https://code.claude.com/docs/en/discover-plugins
- Claude Code setup (Windows): https://code.claude.com/docs/en/setup
- Context7 for Claude Code: https://context7.com/docs/clients/claude-code
- Dispatch: https://support.claude.com/en/articles/13947068-assign-tasks-from-anywhere-in-claude-cowork
- GitHub push protection: https://docs.github.com/en/code-security/secret-scanning/introduction/about-push-protection
