# Claude Code Primer for Derek

A plain-language guide to the pieces we use in this project. Reading time: about 10 minutes. Claude walks you through it at the start of Stage B.

## 1. The big picture in one table

Think of Claude Code as a new engineer on your team. These are the things that shape how that engineer works.

| Piece | Plain meaning | Networking analogy | Where it lives | Example in this project |
|-------|---------------|--------------------|----------------|-------------------------|
| Main session | The engineer you talk to. Plans, codes, coordinates. | The core router: everything passes through it | Your conversation | Builds the app, asks you decisions |
| `CLAUDE.md` | Standing orders read at the start of every session | The running config loaded at boot | Project root | "Derek decides", "never leak secrets" |
| Skill | A playbook Claude pulls off the shelf when a task matches | A saved config template or runbook you apply when needed | `.claude/skills/<name>/SKILL.md` | `ship-change`, `decision-card` |
| Subagent | A specialist teammate with its own fresh workspace and limited tools, who does one job and reports back | Offloading work to a dedicated appliance (like a firewall or load balancer) that returns a result | `.claude/agents/<name>.md` | `security-reviewer`, `test-engineer` |
| MCP connector | A standard plug that lets Claude talk to an outside system | A standard management protocol (like NETCONF) that exposes a device's capabilities in a common format | `claude mcp add ...` or a plugin; `.mcp.json` for shared config | GitHub MCP, Context7 |
| Hook | A command that runs automatically at a set moment, every time, no matter what Claude "remembers" | An ACL: applied to every packet, not a suggestion | `.claude/settings.json` (Claude hooks) or `scripts/hooks/` (Git hooks) | gitleaks blocks commits with secrets |
| Permission rules | Allow, ask or deny lists for Claude's actions | Firewall policy: deny beats allow | `.claude/settings.json` | Deny reading `.env`; ask before `git push` |
| Plugin | A package that bundles skills, agents, hooks and connectors for one-click install | A vendor feature pack or software bundle | Installed with `/plugin` | `security-guidance`, `github` |
| Dispatch | Send a task from your phone; it runs on your PC. Coding tasks run in Claude Code. | Out-of-band management: you reach the device remotely but the work happens on the device | Claude mobile and desktop apps | How you kick off and check on this project |

## 2. Skills vs subagents (the key difference)

| | Skill | Subagent |
|---|-------|----------|
| What it is | Instructions and reference material | A separate worker |
| Context | Loads into the current conversation (optionally into a forked one) | Always starts fresh, with only its own instructions, the task and CLAUDE.md |
| Tools | Uses the session's tools (can pre-approve some) | Only the tools listed in its file |
| Cost | Only the one-line description is loaded until used | Uses its own separate context, so it costs extra usage each time |
| Best for | "Here is HOW we do X here" | "Go DO X and tell me the result" |
| How it starts | Automatically when your request matches its description, or by typing `/skill-name` | Automatically when a task matches its description, or by asking ("use the security-reviewer agent") |
| Our examples | `decision-card`, `spotify-api-notes`, `ship-change`, `phase-report` | `spotify-api-researcher`, `security-reviewer`, `test-engineer`, `ui-designer` |

Rule of thumb: if you would hand a new hire a checklist, make it a skill. If you would hand the work to a different person and wait for their report, make it a subagent. They combine well: a subagent can preload skills.

### What a subagent file looks like

```markdown
---
name: security-reviewer
description: Reviews changes for leaked secrets and unsafe token handling. Use before every pull request.
tools: Read, Grep, Glob, Bash
model: sonnet
---
You are the security reviewer for this project. When invoked...
```

The `description` is what Claude reads to decide when to delegate. `tools` limits what it can do (least privilege). `model` picks which Claude model it runs on.

### What a skill file looks like

```markdown
---
name: ship-change
description: Runs the Git workflow for a finished change. Use when a task is done.
---
1. Run the tests...
2. Ask the security-reviewer agent to review the diff...
```

Skills are folders, so they can also hold templates, scripts or reference files next to `SKILL.md`.

## 3. MCP connectors

MCP (Model Context Protocol) is an open standard for connecting AI tools to outside systems. An MCP server exposes a set of tools (for example "create issue", "list pull requests") and Claude calls them.

- **Add one:** `claude mcp add --transport http <name> <url>` or install a plugin that bundles it. Check status with `/mcp`.
- **Scopes:** local (just you, this project), project (shared through `.mcp.json` in the repo) or user (you, all projects).
- **Secrets:** a shared `.mcp.json` can reference environment variables like `${GITHUB_TOKEN}` so the token itself is never committed.
- **Trust:** a connector acts with whatever access its token has. Give it the least access that works (for GitHub: a fine-grained token limited to this one repo).

Why not a Spotify connector? Claude does not need to control your Spotify to build the app, and a third-party server would hold your Spotify tokens. Our app is the Spotify integration.

## 4. Hooks

Two kinds in this project:

- **Git hooks** run on Git events for anyone who commits. Our `pre-commit` hook runs gitleaks and blocks a commit that contains something that looks like a secret.
- **Claude Code hooks** run on Claude events such as `PreToolUse` (before a tool runs; can block it), `PostToolUse` (after a tool runs), `Stop` (when Claude finishes) and `Notification` (when Claude needs you). We add a `PostToolUse` formatter hook after D1, so code is auto-formatted after every edit. `/hooks` shows what is configured.

Key idea: instructions in CLAUDE.md are guidance Claude follows. Hooks and permission rules are enforcement that always happens.

## 5. Permissions

`.claude/settings.json` (shared, committed) and `.claude/settings.local.json` (personal, not committed) hold `allow`, `ask` and `deny` rules. Deny always wins, like a firewall. Our starter rules:

- deny: reading or editing `.env` and `secrets/`, force-push, hard reset
- ask: `git push`, `gh pr merge`, `gh repo create`, `git tag`, `gh release create`

"Ask" rules still prompt even in auto mode, which keeps you in control of anything that leaves your PC.

## 6. Plugins

Plugins bundle the pieces above. The official Anthropic marketplace (`claude-plugins-official`) is available by default. Type `/plugin` to browse (Discover tab) and install. Each install shows what it adds and its context cost. Only install plugins from sources you trust: they run code on your machine.

## 7. Dispatch

You message Claude from your phone; it works on your PC using your files and connectors. Coding tasks run in Claude Code. Your PC must be awake with the Claude desktop app open. It is one continuous conversation you can reach from phone or desktop.

## 8. Handy commands

| Command | What it does |
|---------|--------------|
| `/help` | List commands |
| `/mcp` | See and sign in to MCP connectors |
| `/plugin` | Browse, install and manage plugins |
| `/hooks` | See configured hooks |
| `/permissions` | See permission rules |
| `/memory` | Edit CLAUDE.md memory files |
| `/context` | See how full the conversation context is |
| `/compact` | Summarize the conversation to free up space |
| `/clear` | Start fresh (good between phases) |
| `/skill-name` | Run a skill by name, for example `/phase-report` |
| Shift+Tab (terminal) | Cycle permission modes, including plan mode (plan only, no edits) |

## 9. Saving usage

- One phase per session; `/clear` between phases. CLAUDE.md and the plan files bring Claude back up to speed.
- Subagents run on `sonnet` and only when needed.
- Ask for "short" when you only need a quick answer.

## 10. Glossary

| Term | Meaning |
|------|---------|
| Repo | The project folder tracked by Git, plus its copy on GitHub |
| Commit | A saved snapshot of changes with a message |
| Branch | A separate line of work so `main` stays stable |
| Pull request (PR) | A request to merge a branch into `main`, with review and checks |
| CI | Continuous Integration: GitHub runs tests and scans on every PR |
| SemVer | Version numbers like v1.4.2 (major.minor.patch) |
| Secret scanning | Automatic search for passwords, keys and tokens in code |
| OAuth 2.0 | The standard "sign in with X" permission system |
| PKCE | A way to do OAuth safely in apps that cannot hide a secret |
| Access token | Short-lived pass (about 1 hour) the app shows Spotify on each request |
| Refresh token | Longer-lived pass used to get new access tokens (Spotify: expires 6 months after sign-in) |
| Endpoint | One URL and method in an API, like `GET /me/playlists` |
| Rate limit | Spotify's cap on requests; exceeding it returns HTTP 429 |
| Loopback | 127.0.0.1, the PC talking to itself; used to catch the sign-in redirect |
| Fisher-Yates | The standard algorithm for a perfectly fair shuffle |
