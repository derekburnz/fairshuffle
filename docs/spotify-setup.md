# Setting up your Spotify developer app

FairShuffle talks to Spotify through the Spotify Web API, and Spotify only answers apps it knows about. So before the first sign-in you register your own copy of the app in the Spotify Developer Dashboard. Spotify then gives you a **Client ID**, a public name tag that tells Spotify which app is asking. This takes about five minutes and you do it once.

There is no client secret in this project. FairShuffle signs in with Authorization Code and PKCE, which proves who it is with a fresh one-time code on every sign-in instead of a stored password. The dashboard can show a client secret: leave it hidden, never copy it anywhere and never put it in `.env`.

## Before you start

- **Spotify Premium on the account that will own the app.** Since February 2026 Spotify only lets Premium accounts run apps in development mode, which is the mode every new app starts in.
- **The FairShuffle repo cloned on your PC** with `uv sync` done, as in the [README](../README.md#developer-setup).
- **A web browser** signed in to that Spotify account.

## 1. Create the app

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and log in with your Spotify account. Accept the Developer Terms if you are asked.
2. Click **Create app** and fill in the form:

   | Field | What to enter |
   |-------|---------------|
   | App name | A name **without the word "Spotify"**, for example `FairShuffle Dev`. Spotify's rules don't allow app names that use or sound like its brand. |
   | App description | `Reorders my own playlists with a true random shuffle.` |
   | Website | Optional. The repo URL is fine. |
   | Redirect URIs | `http://127.0.0.1:8888/callback`, typed exactly like that, then click **Add**. |
   | Which API/SDKs are you planning to use? | Tick **Web API** only. |

3. Tick the box to agree to Spotify's terms and click **Save**.

### Why the Redirect URI looks like that

After you approve the sign-in in your browser, Spotify sends the browser back to the Redirect URI with a one-time code. FairShuffle runs a tiny web listener on your own PC to catch it, so the address must point at your PC:

- `127.0.0.1` is the loopback address: traffic to it never leaves your PC, like a loopback interface on a router. Spotify **does not allow the word `localhost`** here, only the IP address.
- `8888` is the port the listener uses. Plain `http` is fine because the traffic never leaves the machine; Spotify only allows `http` for loopback addresses.
- `/callback` is the path the listener answers on.

The value must match `SPOTIFY_REDIRECT_URI` in your `.env` character for character, or Spotify refuses the sign-in.

## 2. Copy the Client ID into `.env`

1. Open your new app in the dashboard and go to **Settings**. Under **Basic Information** you'll see the **Client ID**. Do not click "View client secret"; FairShuffle never needs it.
2. In PowerShell, in the project folder, make your own `.env` from the template:

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

3. Replace `your-client-id-here` with your Client ID. Leave `SPOTIFY_REDIRECT_URI` as `http://127.0.0.1:8888/callback`. Save and close Notepad.

`.env` is listed in `.gitignore`, so Git never commits it, and Claude Code's settings block its file tools from reading it. Keep your Client ID out of commits, issues, pull requests, screenshots and chat. It is not a password, but it is tied to your Spotify account and to your app's user limit, so the project treats it as private (Rule 2 in `CLAUDE.md`).

## 3. Check who can sign in

An app in development mode works for at most five Spotify accounts, and only the ones listed on its **User Management** page. If sign-in later says your account isn't registered for the app, open **User Management** in the dashboard and add your own name and Spotify account email. Add a friend the same way if you want them to try FairShuffle; they also need Premium.

## 4. Make a test playlist (for later)

Before FairShuffle ever writes to a real playlist (milestone M4), it runs on a throwaway one. Whenever you have a minute, create a playlist called **Shuffle Test** with about 30 songs you don't mind seeing reordered. Sign-in (M2) and listing playlists (M3) only read from Spotify, so nothing changes until then.

## If something goes wrong

| What you see | Likely cause | Fix |
|--------------|--------------|-----|
| `INVALID_CLIENT: Invalid redirect URI` in the browser | The Redirect URI in the dashboard and `SPOTIFY_REDIRECT_URI` in `.env` differ (often `localhost`, a missing `/callback` or another port) | Make both read `http://127.0.0.1:8888/callback` exactly |
| `INVALID_CLIENT: Invalid client` | The Client ID in `.env` is wrong or has extra spaces | Copy it again from the dashboard's Settings page |
| Sign-in says your account isn't registered | Your account isn't on the app's User Management list | Add it, as in step 3 |
| The dashboard won't let you create or use the app | The owner account doesn't have Premium | Use a Premium account to own the app |

## What lives where

| Value | Where it is kept | In Git? |
|-------|------------------|---------|
| Client ID | `.env` in your project folder | Never |
| Redirect URI | `.env`, and the app's settings in the dashboard | `.env.example` holds the standard one |
| Client secret | Nowhere. Not used | Never |
| Sign-in tokens (M2) | Windows Credential Manager and the app's memory, never a file | Never |

The facts in this guide come from the project's checks of Spotify's developer docs (see `.claude/skills/spotify-api-notes/SKILL.md` for the dates). If the dashboard looks different from what is written here, say so in an issue so the guide can be updated.
