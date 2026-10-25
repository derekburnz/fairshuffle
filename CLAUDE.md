# CLAUDE.md: Playlist Shuffler (working name)

Claude Code loads this file at the start of every session in this folder. It holds the standing rules. The full plan lives in `docs/planning/`.

## The project in one paragraph

A Windows 11 desktop app that lives in the system tray (the hidden icons flyout behind the `^` arrow on the taskbar). The user picks one of their Spotify playlists and the app rewrites that playlist's order with a true uniform random shuffle (Fisher-Yates) through the Spotify Web API. The user then plays the playlist from track 1 with Spotify's own shuffle turned off. Inspired by stevenaleong.com/tools/spotifyplaylistrandomizer, but as a downloadable tray app. It is also a resume portfolio project, so the repo, commits, pull requests and docs must look like a professional team project.

## Who you are working with

Derek, a fourth-year Bachelor of IT (Networking) student. This is one of his first Claude Code projects and his first time using agents, skills and MCP connectors. Teach as you go: say what you are doing and why, briefly, in plain language. He wants to understand every tool well enough to explain it in a job interview. Networking analogies help (he knows routing, switching, BGP, MPLS and enterprise IT admin).

## Rule 1: Derek makes the decisions (most important rule)

- Any time there is a choice between options, or between doing something and not doing it, STOP and ask Derek. Do not choose for him, even when one option looks clearly better. Give your recommendation, then wait.
- This covers: languages, libraries, frameworks, folder structure, naming, UI layout, which feature or phase to work on next, installing any tool, plugin, MCP server, agent or skill, creating any GitHub resource, tagging releases and deleting anything.
- Use the Decision Card format below (the `decision-card` skill holds the full template once installed). Use the AskUserQuestion tool when it is available so Derek can tap an option; otherwise post the card as text and end your turn.
- When several next steps are valid (for example UI next, sync next or bug fixes next), present a "What's next?" card and let Derek pick.
- Small mechanical steps inside an already approved task (fixing a typo you made, running tests, formatting) do not need a card. If unsure whether something counts, ask.
- Record every answer in `docs/planning/DECISIONS.md`: ID, date, choice and a one-line reason.

### Decision Card format

```
DECISION D#: <short title>
Why it matters: <one sentence>

| Option | Pros | Cons | Effort |
|--------|------|------|--------|
| A. ... | ...  | ...  | Low    |
| B. ... | ...  | ...  | Medium |

Recommendation: <option>, because <one line>.
Reply with A or B (or "explain more").
```

Readable in under 30 seconds. At most 4 options. Only expand into detail when Derek asks.

## Rule 2: Never leak secrets

- Spotify sign-in uses Authorization Code with PKCE, so there is no client secret. Never create, request or store a Spotify client secret.
- The Spotify Client ID lives only in the local `.env` file, which is gitignored. Commit `.env.example` with placeholder values only.
- Access and refresh tokens are stored only in Windows Credential Manager (through the chosen stack's keyring library). Never in files inside the repo, never in logs, never printed in chat or in test output.
- `.env` is blocked from your file tools by `.claude/settings.json`. Do not try to read it another way. If you need to know whether a value is set, ask Derek. Never ask him to paste a secret or token into the chat.
- Tests use obviously fake values such as `fake-client-id-for-tests`. Never call the real Spotify API from automated tests. Recorded HTTP fixtures must have tokens redacted.
- Before every commit the gitleaks pre-commit hook runs. Before every pull request the `security-reviewer` agent reviews the diff.
- Keep Derek's personal details (email, home paths, account names) out of code, docs, fixtures and logs.
- If a secret is ever committed or pushed: stop, tell Derek immediately, rotate the secret first and only rewrite history with his approval.

## Rule 3: Workplace-grade Git workflow

- After the first commit, never commit directly to `main`. Work on branches named `feat/<issue#>-<short-name>`, `fix/...`, `docs/...`, `test/...`, `chore/...`, `ci/...`.
- Use Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`). Small, focused commits with clear messages.
- Every change reaches `main` through a pull request: template filled in, linked to its issue (`Closes #12`), CI green and security review passed. Claude then squash-merges it and tells Derek (P0-21), and GitHub deletes the branch.
- Each phase is a GitHub milestone. Each goal is broken into issues. Versions follow SemVer tags (`v0.1.0` and up).
- Push branches freely and close each milestone when its phase is done, then carry on to the next phase (P5-2). Ask before: creating repos, tagging, creating releases, changing repo settings. Never force-push, never rewrite `main` history, never delete branches, tags or repos without asking.
- Remote Control and testing on Derek's PC are allowed whenever a task needs them (P5-3). Say what runs there and why.
- Commits use Derek's GitHub noreply email address, not his personal email.

## Rule 4: Verify Spotify API facts before coding against them

Spotify changed the Web API heavily in 2026 and model training data is out of date. Before writing or changing any Spotify API call, check the `spotify-api-notes` skill and confirm against the official docs (the `spotify-api-researcher` agent does this). Headline facts, verified September 24, 2026 and re-checked October 21, 2026:

- Playlist endpoints are `/playlists/{id}/items`. The old `/tracks` paths are listed as removed for development mode apps created after Feb 11, 2026 (deprecated on their reference pages); never call them.
- `GET /playlists/{id}/items` returns at most 50 items per page and only works for playlists the user owns or collaborates on.
- `PUT /playlists/{id}/items` either reorders (`range_start`, `insert_before`, `range_length`, `snapshot_id`) or replaces (`uris`, max 100), never both in one request.
- Redirect URI must be a loopback IP such as `http://127.0.0.1:PORT/callback`. The word `localhost` is not allowed.
- Refresh tokens expire 6 months after the original sign-in. Refreshing does not extend that. An expired token returns `400 invalid_grant`: do not retry, send the user back through sign-in.
- Development mode: app owner needs Premium, max 5 users per app, 429 responses carry `Retry-After`.

## Communication style with Derek

- Lead with the answer. Short. Plain words. Explain jargon the first time it appears.
- No emojis. No em dashes or en dashes. No Oxford commas. No filler openers ("Great question") and no hedging phrases ("it's worth noting", "importantly").
- Prose by default. Tables for comparisons and Decision Cards. Lists only when they help.
- End each work session with a three-line status: done, next options, anything blocked.

## Where things are

| Path | What it is |
|------|------------|
| `docs/planning/PROJECT_PLAN.md` | Master plan: research, architecture, toolkit, roadmap |
| `docs/planning/DECISIONS.md` | Decision Cards and the decision log |
| `docs/planning/CLAUDE_CODE_PRIMER.md` | Beginner guide to agents, skills, MCP, hooks, plugins |
| `docs/planning/ROADMAP.md` | Final roadmap: architecture, Phase 0 checklist, milestones and issues |
| `docs/architecture.md` | How the app is built today: modules, threads, sign-in and shuffle flows, where data lives |
| `docs/spotify-setup.md` | How to register your own Spotify developer app and fill in `.env` |

## Current status

Stage A (research verification) complete on 2026-09-24. Stage B complete on 2026-10-09 (D1 to D8 logged in DECISIONS.md: Python with PySide6, name FairShuffle, public MIT repo). Stage C complete on 2026-10-13 (roadmap in `docs/planning/ROADMAP.md`, tooling D18 to D24 logged: Python 3.14, uv, ruff + pyright + pytest, PySide6-Essentials, src layout, pre-commit framework, CI on Windows). Phase 0 complete on 2026-10-20 (P0-1 to P0-24 logged, report signed off by Derek): public repo `fairshuffle` with a protected `main`, secret scan, Dependabot, issues and the Roadmap board. Phase 1 complete on 2026-10-20 (P1-1 to P1-3 logged): issues #3 to #9 merged (tray icon, About, single-instance guard, logging with redaction, README and architecture notes), Derek checked it from source on Windows and v0.1.0 is released. Phase 2 complete on 2026-10-21 (P2-1 to P2-6 logged): issues #10 to #17 and #83 merged (PKCE sign-in with a loopback listener, refresh token in Credential Manager, the Spotify client core, tray sign in and sign out with "Signed in as", the setup guide), sign-in asks for the playlist scopes plus `user-read-private` (P2-4), Derek checked it on Windows with his own Spotify app and v0.2.0 is released. Phase 3 complete on 2026-10-21 (D11, P2-7, P3-1 and P3-2 logged): issues #18 to #23 merged (playlist listing and item reading through `/me/playlists` and `/playlists/{id}/items`, the picker window opened from the tray, the snapshot_id items cache, empty, error and long-list states), Derek checked the picker with his real playlists on Windows and v0.3.0 is released. Phase 4 complete on 2026-10-25 (D12, D13, P3-3 and P4-1 to P4-7 logged): issues #24 to #31 merged (Fisher-Yates engine with secrets.SystemRandom, fast replace and keep-order reorder writers, backups with Undo, read-back verify, the runner, the live test script), the live test passed on Derek's "Shuffle Test" playlist after two fixes it found (P4-6 compare the songs, re-read when Spotify's reads lag a write) and v0.4.0 is released. Phase 5 (M5, the Shuffle and Undo buttons in the picker, the build tool and the pre-release) started on 2026-10-25 (P4-8, P5-1 to P5-3 logged). On 2026-10-25 D26 to D28 added a new Phase 6 (M6, v0.6.0): a player window with a true shuffle toggle that plays a Fisher-Yates order in the Spotify app without rewriting the playlist; later milestones moved to M7 (bug fixes, v0.7.x), M8 (polish, v0.9.0) and M9 (final, v1.0.0). The name stays FairShuffle (D27). Update this line whenever a stage or phase completes.
