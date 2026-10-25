# Decisions

Every choice in this project is Derek's. Claude presents one card at a time, when it is needed, then waits. Cards below are pre-researched drafts; Claude refreshes them in Stage A if facts changed.

**How to answer:** reply with the letter. Add "explain more" for detail. For multi-select cards, reply "all recommended" or list what to change.

## Decision log

Claude fills this in after each answer.

| ID | Decision | Choice | Date | Reason (one line) |
|----|----------|--------|------|-------------------|
| D1 | Language and framework | A. Python | 2026-10-09 | Python is what Derek knows best; stick with it as much as possible. |
| D2 | UI toolkit | A. PySide6 (Qt) | 2026-10-09 | One toolkit for tray and windows, easier to polish. |
| D3 | App and repo name | B. FairShuffle (`fairshuffle`) | 2026-10-09 | Explains the value in one word; no clash found on the web or PyPI. |
| D4 | Repo visibility | A. Public from day one; keep `docs/planning/` public | 2026-10-09 | Secret-safety layers fit a public repo; visible history and planning trail are portfolio evidence. |
| D5 | License | A. MIT | 2026-10-09 | Simplest and most common for portfolio projects. |
| D6 | Workflow level | A. Full team workflow | 2026-10-09 | Closest to a real job and the best resume signal. |
| D7 | Claude Code toolkit | All recommended plus docs-writer and pr-review-toolkit; not commit-commands | 2026-10-09 | Full toolkit; commit-commands overlaps ship-change. |
| D8 | Teaching style | A. Explanatory | 2026-10-09 | Claude explains each implementation choice; switch to Learning per phase if wanted. |
| D9 | Spotify library or own client | B. Own small client on requests (the card added the HTTP library: A spotipy, B own client on requests, C own client on httpx, D own client on urllib) | 2026-10-21 | requests is the maintained industry default, and our own client gives full control of retries, pacing and log redaction. |
| D10 | Token storage | A. Windows Credential Manager through keyring (refresh token under service FairShuffle; access token in memory only) | 2026-10-21 | The standard way Windows apps keep secrets; matches Rule 2 with the least custom security code. |
| D11 | Tray UI shape | B. Tray menu plus a small picker window (search, item counts, Refresh, Shuffle and a progress bar); mockup in `docs/screenshots/d11-picker-window.png` | 2026-10-21 | Search and the keyboard handle any library size, there is room for progress and Undo, and it still feels like a tray utility. |
| D12 | Shuffle strategy | Fast replace by default, reorder as a setting (option D with the default reversed, in Derek's words): a shuffle rewrites the playlist in chunks of 100 (about 5 calls for 500 songs), and a setting switches to reorder in place, which keeps "date added", "added by" and local files and warns that it is slower | 2026-10-21 | Speed matters most day to day; the slower mode stays one setting away for playlists where the added dates matter. |
| D13 | Backup and undo | A. Automatic backup plus one-click "Undo last shuffle": the order is saved to a local file before the first write and Undo writes it back | 2026-10-21 | The backup adds no Spotify calls (the app already reads every song to shuffle), so it costs no speed, and a fast rewrite cut off halfway needs a quick way back. |
| D14 | Backlog features | pending (Phase 5) | | |
| D15 | Distribution format | pending (Phase 9) | | |
| D16 | Code signing | pending (Phase 9) | | |
| D17 | Client ID in release builds | pending (Phase 9) | | |
| D18 | Python version | A. Python 3.14 | 2026-10-13 | Newest stable branch; every library we need supports it. |
| D19 | Project and dependency manager | A. uv | 2026-10-13 | One tool installs Python, the venv and a lockfile; common choice for new Python projects. |
| D20 | Code quality tools | A. ruff + pyright + pytest | 2026-10-13 | One type checker shared by Claude, the editor and CI. |
| D21 | Qt package | A. PySide6-Essentials | 2026-10-13 | Smaller and covers every feature in the roadmap. |
| D22 | Source layout | A. src layout (`src/fairshuffle/`) | 2026-10-13 | Professional default; protects the Phase 5 build. |
| D23 | Where auto-formatting runs | C. pre-commit framework (plus Claude hook from D7 and CI) | 2026-10-13 | Derek asked for whatever is closest to industry practice; most Python teams commit a .pre-commit-config.yaml. |
| D24 | CI runners | B. Everything on Windows | 2026-10-13 | Focus on Windows for now. Secret scan stays on Ubuntu (gitleaks action only documented there). |
| D25 | Build tool for the .exe | pending (Phase 5) | | |
| D26 | Where the true shuffle player goes | A. A new phase after M5: M6 "True shuffle player" (v0.6.0). A player window lists your playlists and has a true shuffle toggle that turns Spotify's shuffle off and plays a Fisher-Yates order in your Spotify app without rewriting the playlist | 2026-10-25 | Features first, then a feature freeze for hardening and polish (the industry pattern), so both later phases cover the player and Phase 5 is unchanged. |
| D27 | Rename now that FairShuffle is a player too | A. Keep FairShuffle; README and About gain the tagline "a true shuffle player for Spotify" when the player ships (P6-07) | 2026-10-25 | Spotify's Developer Terms (VII.1.3), Developer Policy (VI.2) and design guidelines rule out names with "Spotify" in them (Spotify Plus, Spotify+, TrueSpotify); FairShuffle still names what the toggle does and a rename would force a new sign-in for no gain. |
| D28 | How the player phase shows on GitHub | A. Renumber: the player is M6 (v0.6.0), bug fixes and hardening become M7 (v0.7.x), visual polish M8 (v0.9.0) and the final project M9 (v1.0.0); three milestones renamed, the planning IDs in the open issues updated, the M6 milestone and its 8 issues created, and this docs branch pushed | 2026-10-25 | Milestone order matches release order, so the board, the roadmap and the versions stay in step. |
| C-SIGN | Stage C roadmap sign-off | Approve (ROADMAP.md) | 2026-10-09 | Follows D1 to D8; locked with D18 to D24 on 2026-10-13. |
| P0-1 | Phase 0 step 1: folder layout | Move and sync (package contents moved to the project root, docs synced) | 2026-10-13 | Standard repo layout keeps rules, README and config at the root. |
| P0-2a | Install Git for Windows 2.55 | Just for you (winget, per-user scope) | 2026-10-13 | Same Git; no admin prompt needed, common on locked-down company laptops. |
| P0-2b | Remaining installs | Standing approval for every install the project needs (GitHub CLI, gitleaks, uv, Python 3.14 through uv, later plugins), per-user like Git | 2026-10-13 | Derek typed it in the Phase 0 thread; GitHub changes, pushes and deletions are still asked one at a time. |
| P0-2c | Git install scope (replaces P0-2a) | All users (C:\Program Files\Git), installed when Derek is at the PC to approve the admin prompt | 2026-10-13 | Per-user failed: Git's installer requires admin for administrator accounts; Program Files is the standard location. |
| P0-2d | Where Claude runs on the PC | Terminal session: Claude Code command-line app started from a terminal in the project folder | 2026-10-13 | The desktop app's sandbox redirects AppData writes (uv's Python landed out of reach); the CLI is how most developers run Claude Code. |
| P0-3 | uv build pin in pyproject.toml | Match uv 0.13 (`uv_build>=0.13,<0.14`; ROADMAP 3.6 row updated to uv 0.13.1) | 2026-10-14 | What uv itself writes for a new project today, so uv builds with the copy it already has. |
| P0-4 | Line endings | LF everywhere: `.gitattributes` with `* text=auto eol=lf`, added with the step 4 files | 2026-10-14 | One rule in the repo for every machine, including the Windows CI runners that default to CRLF. |
| P0-5 | Claude on the PC while Derek is away | Desktop app session in the project folder until Derek is back (uses his python.org Python 3.14.7, no uv Python download); the terminal session from P0-2d follows when he is at the PC | 2026-10-14 | Keeps Phase 0 moving; nothing permanent changes. |
| P0-6 | Old kickoff files at the root | Move `00_START_HERE.txt` and `DISPATCH_KICKOFF.txt` into `docs/planning/` before the first commit | 2026-10-14 | The root keeps only real project files; the notes stay as history beside the plan. |
| P0-7 | Public name on commits and license | Full name: git `user.name` and the MIT `LICENSE` say Derek Burns; PROJECT_PLAN owner line stays; email stays the GitHub noreply address | 2026-10-14 | Portfolio work credited to him directly; contact details stay private. |
| P0-8 | gitleaks pre-commit hook on a PC with Smart App Control | Use the installed gitleaks: hook id `gitleaks-system` runs the official winget gitleaks 8.30.1 on PATH | 2026-10-19 | Smart App Control blocked the unsigned gitleaks pre-commit built from source; the scan still runs before every commit without weakening Windows. |
| P0-9 | Where the approved Claude plugins are switched on | This project: `enabledPlugins` in the repo's `.claude/settings.json` (`--scope project`), committed on a branch and merged by pull request | 2026-10-19 | Shared tooling lives in the repo so every clone and Claude session gets the same setup. |
| P0-10 | Security reviewer hardening ideas | All three: PowerShell deny rules and `.env.*` deny rules (with `.env.example` carved out) in `.claude/settings.json`; `.gitignore` ignores every `.env.*` except `.env.example`; secret-scan actions pinned to commit SHAs | 2026-10-19 | Commit-pinned actions follow GitHub's hardening guide, and both `.env` gaps back up Rule 2. |
| P0-11 | Create the GitHub repo and push | Create and push main: public `derekburnz/fairshuffle` with the roadmap description, local repo linked as `origin`, `main` pushed; plugin and hardening branches follow as pull requests after step 8 | 2026-10-19 | Approved in the roadmap and every check passed; pushing now lets branch protection go on before other changes land. |
| P0-12 | Step 8 repo settings and issues | All of step 8: ruleset "Protect main" (pull request required with 0 reviews because GitHub blocks approving your own pull request, `gitleaks` check required, no force push or deletion), squash merge only with merged branches deleted, secret scanning, push protection and Dependabot alerts and fixes on, 10 labels, milestones M1 to M8, a Roadmap project board and 54 issues (52 from ROADMAP section 5 plus 2 for the Phase 0 branches) | 2026-10-19 | This is how team repos run; Derek's Merge click is the approval. |
| P0-13 | Order of the Phase 0 pull requests | Plugin PR first: push `chore/phase-0-plugins` and open its pull request for #1; replay the hardening branch onto `main` after that merge, then open its pull request for #2 | 2026-10-19 | One reviewable change at a time keeps `main` history clean and needs no force push. |
| P0-14 | Extra clone inside the project folder | Delete it: remove the nested `fairshuffle/` copy that VS Code cloned inside the project folder after confirming it holds nothing beyond GitHub `main` | 2026-10-19 | One working copy per machine; the nested copy lacked the open branches and would be swept in by `git add -A`. |
| P0-15 | Dependabot comment in `secret-scan.yml` | Add Dependabot: `.github/dependabot.yml` checks GitHub Actions and uv weekly and opens update pull requests labelled `type:ci` or `type:chore` | 2026-10-19 | Automated dependency updates are standard on team repos and keep the SHA-pinned actions current, so the workflow comment becomes true. |
| P0-16 | Secret-scan workflow token | Read plus comments: `secret-scan.yml` sets the workflow token to `contents: read`, and the scan job also gets `pull-requests: write` so gitleaks can comment on the line where it finds a secret | 2026-10-19 | Least privilege is GitHub's hardening advice for workflow tokens, and the comments keep the scan's feedback useful. |
| P0-17 | Checkout token in the secret-scan runner | Add it: the checkout step in `secret-scan.yml` sets `persist-credentials: false`, so no token copy stays in the runner's `.git/config` | 2026-10-19 | gitleaks reads its token from the environment, so the saved copy only adds risk; security linters such as zizmor flag it. |
| P0-18 | Remaining Phase 0 steps | Go ahead without a card for each: Derek read and approved the issue list, and Claude finishes Phase 0 through issues #57 (pyright-lsp plugin) and #58 (starter-kit removal) with branches and pull requests; merges stay Derek's click and new design choices still get a card | 2026-10-19 | Derek approved the remaining steps after reading every issue. |
| P0-19 | pyright-lsp plugin | Enable `pyright-lsp` at project scope; it starts the `pyright-langserver` on PATH, which is the user-wide copy from P0-20, because Claude Code refuses to start a language server from inside the project folder, so it can't use the `.venv` copy | 2026-10-19 | Live type checking for Claude while it edits, like the editor has, at the version CI uses (D20). |
| P0-20 | Where Claude's pyright comes from | User-wide pyright: Derek runs `uv tool install "pyright[nodejs]==1.1.414"` in his own terminal, the version `uv.lock` pins, and bumps it by hand to match when Dependabot updates the project's pyright | 2026-10-19 | The only way the plugin gets a language server, and a matching pin keeps Claude in step with CI. |
| P0-21 | Who merges pull requests | Claude merges: once a pull request's checks are green and the security-reviewer gives PASS, Claude squash-merges it and tells Derek; Rule 3 in `CLAUDE.md` changes to match, and pushes, tags and releases still need Derek's go-ahead | 2026-10-20 | Keeps work moving between Derek's check-ins, with green checks and the security review still gating every merge. |
| P0-22 | CI workflow when the starter kit is deleted | Delete, note on #4: `ci.yml` goes with the starter-kit folder, and issue #4 (P1-02) gets a comment with the Git command that restores it from history | 2026-10-20 | Git history is the usual record for removed files, and #4 re-pins the actions by commit SHA anyway. |
| P0-23 | GitHub MCP connector (Phase 0 step 6) | Park for later: Phase 0 finishes without it and issue #62 revisits it in M8, while `gh` keeps handling issues and pull requests | 2026-10-20 | `gh` already covers every GitHub step, so a second long-lived token can wait. |
| P0-24 | Phase 0 sign-off and what comes next | Tidy, then Phase 1: Derek signed off the Phase 0 report; one pull request adds Dependabot's `pre-commit` updates, bumps ruff's hook to v0.17.1 and logs P0-23 and P0-24, then Phase 1 starts in its own thread | 2026-10-20 | Closes Phase 0 cleanly so Phase 1 starts on an up-to-date toolchain. |
| P1-1 | Required CI checks on `main` (#4) | Yes, from Derek's PC: `lint and type check (Windows)` and `tests (Windows)` join `gitleaks` as required checks in the "Protect main" ruleset, all tied to GitHub Actions; set with `gh` on Derek's typed go-ahead | 2026-10-20 | Required checks on `main` are standard on team repos, so a red check now blocks the merge. |
| P1-2 | What's next after Phase 1 | Check on my PC, then tag: Derek's PC synced to `main` and he ran FairShuffle from source (icon under `^`, About, a second launch, Quit); on his typed go-ahead v0.1.0 was tagged on b27acfa and released | 2026-10-20 | A person checks a build by hand before it is released, as the M1 definition of done asks. |
| P1-3 | What's next now that v0.1.0 is out | Tidy, then Phase 2: one issue (#72) and one pull request log P1-2 and P1-3 and mark Phase 1 complete, M1 is closed, then Phase 2 starts in its own thread | 2026-10-20 | Closing a milestone before the next one starts keeps the board and the decision log honest, as at the end of Phase 0 (P0-24). |
| P2-1 | Feature branch pushes in M2 | Push freely: Claude pushes feature branches for the rest of M2 without asking and says when each PR is up; tags, releases, repo settings and deletions are still asked one at a time | 2026-10-21 | The protected `main` and the PR checks are the real gate, as on company teams, and work keeps moving while Derek is away. |
| P2-2 | How tests fake Spotify's HTTP replies and block real network | responses (fake replies for requests) plus pytest-socket (any socket other than 127.0.0.1 fails the test); both dev-only | 2026-10-21 | Current, widely used tools, so the tests read like ones at a company, and the guard is configuration instead of custom code. |
| P2-3 | How config.py reads the Client ID in development | python-dotenv reads the gitignored `.env` in the project folder; real environment variables win over the file; the Client ID goes to `mask_secret()` at once. The release build's answer stays with D17 | 2026-10-21 | The usual Python library for `.env` files, small and current, and it keeps the plan and setup guide as written. |
| P2-4 | Scopes for the "Signed in as" name | Add `user-read-private` now: sign-in asks for the four playlist scopes plus `user-read-private`, so `GET /me` can return `display_name`; `user-read-email` is never asked for | 2026-10-21 | Spotify's scopes page lists `user-read-private` as the scope `/me` needs and the docs don't say the name comes back without it, so asking for it avoids a guess; the fields it adds besides the name are gone for development mode apps. |
| P2-5 | Client ID posted in the project chat | Keep it: the same Spotify app and Client ID stay in use and the ID stays only in Derek's `.env`; nothing was saved by Claude | 2026-10-21 | A Client ID is a public identifier under PKCE (it shows in every sign-in URL), development mode limits the app to listed users, and Spotify can't change an app's Client ID short of recreating the app. |
| P2-6 | Release v0.2.0 | Prep, then tag and release: PR #84 set the version to 0.2.0, then on Derek's typed go-ahead his PC tagged v0.2.0 on 960b168 and published the release; one pull request then marks Phase 2 complete | 2026-10-21 | M2's goal (sign in and sign out securely) was met and checked on Derek's PC, and a tag per milestone is how the roadmap tracks progress, as with v0.1.0. |
| P2-7 | What's next after v0.2.0 | Close M2, then Phase 3: the M2 milestone closed from Derek's PC and Phase 3 (M3, v0.3.0) started in its own thread | 2026-10-21 | M2 was released and checked; listing playlists is the next roadmap step and is read-only, so nothing can be damaged. |
| P3-1 | Feature branch pushes in M3 | Push freely: Claude pushes M3 feature branches and opens their PRs without asking each time; tags, releases, repo settings and deletions are still asked one at a time | 2026-10-21 | Same as P2-1: the protected `main`, the PR checks and the security review are the real gate, and work keeps moving while Derek is away. |
| P3-2 | Release v0.3.0 | Tag and release: PR #93 set the version to 0.3.0, Derek checked the picker with his real playlists on his PC, then on his typed go-ahead his PC tagged v0.3.0 on 84d60c3 and published the release (602 tests passed there); one pull request then marks Phase 3 complete | 2026-10-21 | M3's goal (see your playlists) was met and checked on Derek's PC, and a tag per milestone is how the roadmap tracks progress, as with v0.1.0 and v0.2.0. |
| P3-3 | What's next after v0.3.0 | Close M3, then Phase 4: the M3 milestone closed from Derek's PC and Phase 4 (M4, v0.4.0, the shuffle) started in its own thread | 2026-10-21 | M3 was released and checked; the shuffle is the next roadmap step. |
| P4-1 | Feature branch pushes in M4 | Push freely: Claude pushes M4 feature branches and opens their PRs without asking each time; tags, releases, repo settings and deletions are still asked one at a time | 2026-10-21 | Same as P2-1 and P3-1: the protected `main`, the PR checks and the security review are the real gate. |
| P4-2 | Fast mode on a playlist with local files | Ask each time: before a fast shuffle of a playlist holding local files or items Spotify sends no URI for, a dialog says how many would be removed and offers Use keep-order mode, Shuffle fast anyway or Cancel | 2026-10-21 | The API can't add those items back, so neither fast mode nor Undo could restore them; warning before a permanent loss is the standard pattern. |
| P4-3 | Who writes the Fisher-Yates loop (#25) | A. Claude writes it and explains it line by line in the PR; the Explanatory style from D8 stays for all of M4 | 2026-10-21 | Keeps M4 moving without waiting on Derek, and the PR walkthrough still leaves him able to explain the algorithm. |
| P4-4 | Where the keep-order ("keep date added") setting lives | A. A "Keep date added (slower)" checkbox in the picker, above the Shuffle button, remembered between runs; built with the picker's Shuffle and Undo buttons in M5 (#32) | 2026-10-22 | The choice is visible at the moment it matters and needs no extra window. |
| P4-5 | How the live test on "Shuffle Test" runs (#31) | A. A dev-only script, `scripts/live_shuffle_test.py`, run through Remote Control on Derek's PC: 5 fast and 5 keep-order shuffles plus an Undo, each read back and checked, on the "Shuffle Test" playlist only | 2026-10-22 | Keeps the roadmap order (buttons in M5) and gives a repeatable smoke test like teams run before a release. |
| P4-6 | How keep-order mode spots another editor mid-shuffle | A. Compare the songs: every 10 moves (50 in the app) read the playlist and check it matches the order our own moves should have made; the snapshot_id is still sent with each move but no longer compared | 2026-10-22 | The first live run (#31) showed the snapshot_id from GET /playlists/{id} never matches a reorder reply's, so keep-order stopped every time; the songs are what matters and can't false-alarm. Derek added "do whatever is fastest", so the fix rides in PR #102. |
| P4-7 | Release v0.4.0 | Tag and release: PR #103 set the version to 0.4.0, the live test passed on Derek's "Shuffle Test" playlist (10 shuffles and an Undo verified, #102), then on his typed "Release v0.4.0" his PC tagged v0.4.0 on ac60159 and published the release; one pull request then marks Phase 4 complete | 2026-10-25 | M4's goal (a true shuffle written to Spotify, backed up, checked and undoable) was met and checked against the real API, and a tag per milestone is how the roadmap tracks progress. |
| P4-8 | What's next after v0.4.0 | A. Close M4, then Phase 5: the M4 milestone closes and Phase 5 (M5, Shuffle and Undo in the picker) starts in its own thread; the review follow-ups are filed as #107 to #109 | 2026-10-25 | Keeps the roadmap order; the follow-ups are small and sit with the other hardening work. |
| P5-1 | Feature branch pushes in M5 | Yes, push freely for M5 | 2026-10-25 | Same as P2-1, P3-1 and P4-1: the protected `main`, the PR checks and the security review are the real gate. |
| P5-2 | Pushes and milestones from now on | Derek typed: push freely in every phase, take the push prompt out of the settings, and close each milestone and carry on to the next phase when a phase is done. `git push` leaves the "ask" list in `.claude/settings.json` (force-push stays blocked); tags, releases, repo settings and deletions are still asked | 2026-10-25 | Asking at the start of every phase only slowed the work; every change still reaches `main` through a reviewed PR. |
| P5-3 | Remote Control and testing on Derek's PC | Derek typed: allowed for all milestones and phases where needed; Claude still says what it runs there and why | 2026-10-25 | Most checks (Windows-only tests, live runs, builds) need his PC, and asking each time held the work up. |

---

## Stage B cards (before any code)

### D1: Language and framework

Why it matters: it decides what you learn, how the app looks and how big the download is.

| Option | Pros | Cons | Effort |
|--------|------|------|--------|
| A. Python (tray via PySide6 or pystray) | Easiest to read and learn. Fastest to a working prototype. Python is the main language of network automation (Netmiko, NAPALM, Ansible), so the skill carries into your field. spotipy 2.26 already supports the 2026 API. | Larger download (tens of MB). Packaged Python apps are sometimes flagged by antivirus. Needs care to look native. | Low |
| B. C# with .NET 10 (WPF or WinForms) | Most Windows-native look and behaviour. Valued in enterprise and IT roles. Excellent tray support. SpotifyAPI.Web 7.4 supports the 2026 API. Single-file exe. | Windows only. Moderate learning curve. Visual Studio is a heavy install. | Medium |
| C. Tauri 2 (Rust core, TypeScript web UI) | Tiny app (a few MB). Modern web-style UI. Built-in tray, installer and updater. Most impressive stack on a resume. | Two languages. Rust is the hardest to learn. More setup. rspotify 0.16.1 supports the 2026 API, but its last release was April 2026. | High |
| D. Electron (TypeScript) | Huge ecosystem, web UI | 100 MB+ and heavy memory use for a small tray tool | Medium |

Recommendation: A, because you learn fastest, it maps directly to network automation work and Claude can still build a clean, well-tested architecture. Choose C if you want the most technically impressive stack and accept a slower start.
Reply with A, B, C or D.

### D2: UI toolkit (the card shown depends on D1)

Why it matters: it decides how the tray menu and any windows look and how hard polish will be.

If D1 = Python:

| Option | Pros | Cons | Effort |
|--------|------|------|--------|
| A. PySide6 (Qt) | One library for tray icon and real windows. Polished widgets, dark mode, good docs. | Larger install. LGPL license (fine for an MIT app when linked normally). | Medium |
| B. pystray + CustomTkinter | Light and simple. Modern-looking Tk widgets. | Two libraries that need careful threading together. Fewer advanced widgets. | Low |

Recommendation: A, because one well-supported toolkit is easier to polish in Phase 7.

If D1 = C#:

| Option | Pros | Cons | Effort |
|--------|------|------|--------|
| A. WPF with the H.NotifyIcon library | Modern styling (XAML), mature, lots of examples | Some XAML learning | Medium |
| B. WinForms with built-in NotifyIcon | Simplest, built in | Dated look | Low |
| C. WinUI 3 | Most modern Windows 11 look | More complex packaging and tooling | High |

Recommendation: A.

If D1 = Tauri: A. plain TypeScript, B. Svelte, C. React for the web UI. Recommendation: B (small, simple, fast).

### D3: App and repo name

Why it matters: it is on your resume and GitHub profile. Spotify's rules: the name must not include "Spotify" or sound like it; a tagline such as "a true shuffle for Spotify playlists" is fine.

| Option | Repo name | Notes |
|--------|-----------|-------|
| A. TrayShuffle | `trayshuffle` | Says what and where |
| B. FairShuffle | `fairshuffle` | Says why (every song gets a fair chance) |
| C. TrueOrder | `trueorder` | Short, brandable |
| D. Your own idea | | Claude checks it against the Spotify naming rule and looks for existing projects with the same name |

Recommendation: B, because it explains the value in one word. Claude checks GitHub for name clashes before you confirm.
Reply with A, B, C or your own name.

### D4: Repo visibility

Why it matters: recruiters can only see public repos, but public means mistakes are public too.

| Option | Pros | Cons | Effort |
|--------|------|------|--------|
| A. Public from day one | Full commit history shows real engineering process. Branch protection is free on public repos. GitHub push protection for users (blocks known secret formats) applies to public repos. | Early mistakes are visible. Planning docs are visible. | Low |
| B. Private until the prototype or v1.0, then public | Freedom to experiment. Clean reveal. | Branch protection on private repos needs GitHub Pro (free with the Student Developer Pack). History still becomes public when you flip it. | Low |

Recommendation: A, because the secret-safety layers in the plan are built for a public repo and a visible history is the strongest portfolio signal.
Follow-up question if A: keep `docs/planning/` in the public repo (shows your process) or move it out? Claude asks this separately.
Reply with A or B.

### D5: License

Why it matters: without a license, nobody may legally reuse your code, even though they can see it.

| Option | Pros | Cons |
|--------|------|------|
| A. MIT | Simplest and most common for portfolio projects | Anyone can reuse it, even commercially |
| B. Apache 2.0 | Like MIT plus an explicit patent grant | Longer text |
| C. No license (all rights reserved) | Keeps full control | Looks unusual on a public portfolio repo |

Recommendation: A.
Reply with A, B or C.

### D6: How "workplace" the GitHub process should be

Why it matters: more process means more resume evidence and learning, but more steps per change.

| Option | What you get | Pros | Cons |
|--------|--------------|------|------|
| A. Full team workflow | Issues, milestones, Projects board, feature branches, PRs with template, CI, security review, releases, changelog | Closest to a real job. Best resume signal. | A few extra minutes per change |
| B. Standard | Branches, PRs, CI, releases. Issues only for bugs. | Faster | Less planning evidence |
| C. Light | Commit to main, tag releases | Fastest | Weak signal, not what you asked for |

Recommendation: A.
Reply with A, B or C.

### D7: Claude Code toolkit (multi-select)

Why it matters: each tool adds capability but also some setup and some usage. Read `CLAUDE_CODE_PRIMER.md` first (Claude walks you through it).

| Item | Type | What it does for this project | Default |
|------|------|-------------------------------|---------|
| spotify-api-researcher | Agent | Fact-checks Spotify API details before coding | Recommended |
| security-reviewer | Agent | Checks every PR for secrets and unsafe token handling | Recommended |
| test-engineer | Agent | Writes and runs tests with fake Spotify responses | Recommended |
| ui-designer | Agent | Mockups and polish (mostly Phase 7) | Recommended |
| docs-writer | Agent | README, changelog, release notes, resume bullets | Optional |
| decision-card | Skill | Keeps every decision in the same quick format | Recommended |
| spotify-api-notes | Skill | Dated Spotify facts Claude checks before coding | Recommended |
| ship-change | Skill | Test, review, commit, push, PR in one routine | Recommended |
| phase-report | Skill | End-of-phase summary and "What's next?" menu | Recommended |
| GitHub MCP | Connector | Claude manages issues, milestones and PRs through GitHub's API | Recommended |
| Context7 | Connector | Current library documentation on demand | Recommended |
| Language server plugin for your stack | Plugin | Claude sees type errors instantly | Recommended |
| security-guidance | Plugin | Automatic security check on each change | Recommended |
| explanatory or learning output style | Plugin | Teaching mode (decided in D8) | Recommended |
| commit-commands | Plugin | Ready-made git skills | Optional (overlaps ship-change) |
| pr-review-toolkit | Plugin | Extra PR review agents | Optional |
| Permission rules in `.claude/settings.json` | Guardrail | Blocks `.env`, blocks force-push, asks before push, merge and release | Recommended |
| gitleaks pre-commit hook | Guardrail | Blocks commits that contain secrets | Recommended |
| Secret scan CI workflow | Guardrail | Scans every PR on GitHub | Recommended |
| Formatter hook | Guardrail | Auto-formats code after each edit | Recommended |
| GitHub CLI (`gh`) and gitleaks | Tools | Command-line GitHub access and secret scanning | Recommended |

Recommendation: all items marked Recommended. Add docs-writer if you want help with the README and resume bullets later.
Reply "all recommended" or list changes.

### D8: Teaching style

Why it matters: decides how much Claude explains while it codes.

| Option | Pros | Cons |
|--------|------|------|
| A. Explanatory output style | Claude explains why it made each implementation choice | Longer replies, more usage |
| B. Learning output style | Claude leaves small parts for you to write yourself and coaches you | Slower, but you learn to code it yourself |
| C. Default | Fastest | You learn less |

Recommendation: A, and switch to B for a phase you want to write yourself (Phase 4's shuffle engine is a good one). You can switch any time.
Reply with A, B or C.

---

## Stage C cards (tooling, raised by the Python roadmap)

Full options, pros, cons and recommendations are in `ROADMAP.md` section 2 and on the Stage C decision page. Summary: D18 Python version (rec. 3.14), D19 dependency manager (rec. uv), D20 code quality tools (rec. ruff + pyright + pytest), D21 Qt package (rec. PySide6-Essentials), D22 source layout (rec. `src/fairshuffle/`), D23 where auto-formatting runs (rec. Claude hook + git pre-commit check + CI), D24 CI runners (rec. lint on Ubuntu, tests on Windows). D25 build tool (PyInstaller or Nuitka) is asked at the start of Phase 5.

---

## Phase cards (asked when the phase starts)

### D9: Spotify library or own small client (Phase 2)

Why it matters: the Spotify API changed a lot in 2026 and may change again.

| Option | Pros | Cons | Effort |
|--------|------|------|--------|
| A. Use the library (spotipy or SpotifyAPI.Web) | Less code, built-in auth helpers | Can lag behind Spotify changes. Less control over pacing, retries and log redaction. | Low |
| B. Own small HTTP client for the 7 or so endpoints we need | Full control of retries, pacing and logging. No library lag. Shows real HTTP and REST skill. | More code and tests | Medium |
| C. Library for sign-in only, own client for playlist calls | Balance | Two styles in one codebase | Medium |

Recommendation: B, because we only need a handful of endpoints and it is the stronger networking and resume story. (For Tauri, B is effectively required.)

Asked on 2026-10-20 with the HTTP library folded in, since ROADMAP section 2 puts it inside D9. Checked on PyPI that day: spotipy 2.26.0 (March 2026, its default token cache is a plain file), requests 2.34.2 (May 2026), httpx 0.28.1 (no stable release since December 2024). Options asked: A. spotipy, B. own client on requests, C. own client on httpx, D. own client on the standard library's urllib. Derek chose B.

### D10: Token storage (Phase 2)

| Option | Pros | Cons |
|--------|------|------|
| A. Windows Credential Manager (keyring library) | Protected by Windows per user. Standard practice. | Tied to your Windows account |
| B. File encrypted with Windows DPAPI | Also protected per user | More custom code |
| C. Plain file | Simple | Unsafe; any program can read it. Not recommended. |

Recommendation: A.

### D11: Tray UI shape (Phase 3)

| Option | Pros | Cons | Effort |
|--------|------|------|--------|
| A. Tray menu only (playlists in a submenu) | Minimal and fast | Long lists get unwieldy. Hard to show progress. | Low |
| B. Tray menu plus a small picker window (search, song counts, progress bar) | Best experience. Room for progress and settings. | More UI work | Medium |
| C. Full main window that minimizes to tray | Most room for features | Heavier. Loses the "lives in the tray" feel. | High |

Recommendation: B. `ui-designer` shows mockups of each before you choose.

Decided 2026-10-21: B. The `ui-designer` mockups of all three options were shown first; the chosen one is `docs/screenshots/d11-picker-window.png` (fake data, rendered with PySide6). The tray menu keeps its account line, gains "Shuffle a playlist..." (the ellipsis is the Windows sign that it opens a window) and the picker opens at about 380 x 520 with search, the playlist list with item counts, Refresh and Shuffle.

### D12: Shuffle strategy (Phase 4)

Numbers for a 500-song playlist. See PROJECT_PLAN section 2.4.

| Option | Pros | Cons | Effort |
|--------|------|------|--------|
| A. Reorder in place (about 499 calls) | Keeps "date added", "added by" and local files. Same approach as the reference tool. | Slow on big playlists (minutes). More exposure to rate limits. | Medium |
| B. Replace in place (about 5 calls) | Fast (seconds) | Resets "date added" for every song. Local files are lost (confirmed in Stage A: the API cannot add local files). | Low |
| C. Write a shuffled copy (about 6 calls) | Original never touched | Extra playlist. Same losses as B in the copy. | Low |
| D. A by default, B as an opt-in "fast mode" | Best of both | Two code paths to test | High |

Recommendation: A first (safe, preserves everything), with D as a later upgrade if big playlists feel slow.

Decided 2026-10-21: Derek wrote "By default use the fastest method that doesn't preserve those things but have a setting to re-order and preserve those but warn its slower". So both paths are built: replace (B) is the default and reorder in place (A) is a setting that says it is slower. The card was closed as D, whose label has the default the other way round; Derek's words are the decision.

### D13: Backup and undo (Phase 4)

| Option | Pros | Cons |
|--------|------|------|
| A. Automatic backup plus one-click "Undo last shuffle" | Real safety net. Beats the reference tool. | More code |
| B. Automatic backup file only, restore added later | Simple safety | No quick undo |
| C. No backup | Least work | A failed or unwanted shuffle cannot be reversed |

Recommendation: A.

Decided 2026-10-21: A. Derek asked for a backup only if it doesn't slow the shuffle down; it doesn't, because the items are already read for the shuffle and the backup is one local file. He then confirmed A in words.

### D14: Backlog features (end of Phase 5, multi-select)

Pick from PROJECT_PLAN section 9 after you have used the prototype. Claude shows the list with effort estimates.

### D15: Distribution format (Phase 9)

| Option | Pros | Cons |
|--------|------|------|
| A. Portable .exe (zip) on GitHub Releases | Simplest. No install. | No Start menu entry or uninstaller |
| B. Installer | Start menu entry, uninstaller, optional start with Windows | More build setup |
| C. Both | Covers everyone | Twice the release testing |

Recommendation: C if time allows, otherwise A.

### D16: Code signing (Phase 9)

| Option | Pros | Cons |
|--------|------|------|
| A. Unsigned, README explains the SmartScreen "More info, Run anyway" step | Free | Warning puts some users off |
| B. Paid code-signing certificate or signing service | Fewer warnings, professional | Ongoing cost and identity verification (Claude checks current prices) |
| C. Source only, with build instructions | No warning issue | Inconvenient for non-developers |

Recommendation: A for a portfolio project.

### D17: Client ID in release builds (Phase 9)

Why it matters: development mode apps allow only 5 users, all allowlisted by the owner.

| Option | Pros | Cons |
|--------|------|------|
| A. Each user enters their own Client ID on first run (guide in README) | Works for anyone. No limit on your app. Nothing of yours ships in the build. | Extra 5-minute setup for each user |
| B. Your Client ID built into the release | One-click for up to 4 friends you allowlist | Everyone else is blocked. Your ID is visible in the build (not a secret under PKCE, but it counts against your limits). |

Recommendation: A, with B available as a private build for friends.

## Feature planning cards (2026-10-25)

Asked in the "Plan true shuffle playback feature" thread after v0.4.0. Derek asked for a Spotify-like view of his playlists with a "true shuffle" toggle that turns Spotify's shuffle off and plays songs in a fair random order without rewriting the playlist, and floated renaming the app to Spotify Plus, Spotify+ or TrueSpotify. The official docs were checked first (Rule 4): every Player endpoint is still available in development mode, play and shuffle need Premium for every user, and Spotify's terms forbid "Spotify" in an app name. Answers are in the log above; the plan is ROADMAP.md M6.

Derek added two requirements on 2026-10-25, written into M6: each playlist shows its own Spotify cover picture, because pictures are easier to recognise than names (P6-05), and after turning the toggle on he can go back to the Spotify app and the playlist keeps playing there in the random order (P6-04).

---

## Anytime card: "What's next?"

Claude uses this whenever more than one next step makes sense.

```
WHAT'S NEXT?
Done: <one line>

| Option | What it gets you | Effort |
|--------|------------------|--------|
| A. <next roadmap step> | ... | ... |
| B. <alternative, for example UI work> | ... | ... |
| C. <alternative, for example bug fixes> | ... | ... |
| D. Stop here and write a status report | Clean pause point | Low |

Recommendation: <option>, because <one line>.
```
