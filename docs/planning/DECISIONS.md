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
| D9 | Spotify library or own client | pending (Phase 2) | | |
| D10 | Token storage | pending (Phase 2) | | |
| D11 | Tray UI shape | pending (Phase 3) | | |
| D12 | Shuffle strategy | pending (Phase 4) | | |
| D13 | Backup and undo | pending (Phase 4) | | |
| D14 | Backlog features | pending (Phase 5) | | |
| D15 | Distribution format | pending (Phase 8) | | |
| D16 | Code signing | pending (Phase 8) | | |
| D17 | Client ID in release builds | pending (Phase 8) | | |
| D18 | Python version | A. Python 3.14 | 2026-10-13 | Newest stable branch; every library we need supports it. |
| D19 | Project and dependency manager | A. uv | 2026-10-13 | One tool installs Python, the venv and a lockfile; common choice for new Python projects. |
| D20 | Code quality tools | A. ruff + pyright + pytest | 2026-10-13 | One type checker shared by Claude, the editor and CI. |
| D21 | Qt package | A. PySide6-Essentials | 2026-10-13 | Smaller and covers every feature in the roadmap. |
| D22 | Source layout | A. src layout (`src/fairshuffle/`) | 2026-10-13 | Professional default; protects the Phase 5 build. |
| D23 | Where auto-formatting runs | C. pre-commit framework (plus Claude hook from D7 and CI) | 2026-10-13 | Derek asked for whatever is closest to industry practice; most Python teams commit a .pre-commit-config.yaml. |
| D24 | CI runners | B. Everything on Windows | 2026-10-13 | Focus on Windows for now. Secret scan stays on Ubuntu (gitleaks action only documented there). |
| D25 | Build tool for the .exe | pending (Phase 5) | | |
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

### D12: Shuffle strategy (Phase 4)

Numbers for a 500-song playlist. See PROJECT_PLAN section 2.4.

| Option | Pros | Cons | Effort |
|--------|------|------|--------|
| A. Reorder in place (about 499 calls) | Keeps "date added", "added by" and local files. Same approach as the reference tool. | Slow on big playlists (minutes). More exposure to rate limits. | Medium |
| B. Replace in place (about 5 calls) | Fast (seconds) | Resets "date added" for every song. Local files are lost (confirmed in Stage A: the API cannot add local files). | Low |
| C. Write a shuffled copy (about 6 calls) | Original never touched | Extra playlist. Same losses as B in the copy. | Low |
| D. A by default, B as an opt-in "fast mode" | Best of both | Two code paths to test | High |

Recommendation: A first (safe, preserves everything), with D as a later upgrade if big playlists feel slow.

### D13: Backup and undo (Phase 4)

| Option | Pros | Cons |
|--------|------|------|
| A. Automatic backup plus one-click "Undo last shuffle" | Real safety net. Beats the reference tool. | More code |
| B. Automatic backup file only, restore added later | Simple safety | No quick undo |
| C. No backup | Least work | A failed or unwanted shuffle cannot be reversed |

Recommendation: A.

### D14: Backlog features (end of Phase 5, multi-select)

Pick from PROJECT_PLAN section 9 after you have used the prototype. Claude shows the list with effort estimates.

### D15: Distribution format (Phase 8)

| Option | Pros | Cons |
|--------|------|------|
| A. Portable .exe (zip) on GitHub Releases | Simplest. No install. | No Start menu entry or uninstaller |
| B. Installer | Start menu entry, uninstaller, optional start with Windows | More build setup |
| C. Both | Covers everyone | Twice the release testing |

Recommendation: C if time allows, otherwise A.

### D16: Code signing (Phase 8)

| Option | Pros | Cons |
|--------|------|------|
| A. Unsigned, README explains the SmartScreen "More info, Run anyway" step | Free | Warning puts some users off |
| B. Paid code-signing certificate or signing service | Fewer warnings, professional | Ongoing cost and identity verification (Claude checks current prices) |
| C. Source only, with build instructions | No warning issue | Inconvenient for non-developers |

Recommendation: A for a portfolio project.

### D17: Client ID in release builds (Phase 8)

Why it matters: development mode apps allow only 5 users, all allowlisted by the owner.

| Option | Pros | Cons |
|--------|------|------|
| A. Each user enters their own Client ID on first run (guide in README) | Works for anyone. No limit on your app. Nothing of yours ships in the build. | Extra 5-minute setup for each user |
| B. Your Client ID built into the release | One-click for up to 4 friends you allowlist | Everyone else is blocked. Your ID is visible in the build (not a secret under PKCE, but it counts against your limits). |

Recommendation: A, with B available as a private build for friends.

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
