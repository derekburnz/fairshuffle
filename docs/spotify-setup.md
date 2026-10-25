# Setting up your Spotify developer app

FairShuffle talks to Spotify through the Spotify Web API, and Spotify only answers apps it knows about. So before the first sign-in you register your own copy of the app in the Spotify Developer Dashboard. Spotify then gives you a **Client ID**, a public name tag that tells Spotify which app is asking. This takes about five minutes and you do it once.

There is no client secret in this project. FairShuffle signs in with Authorization Code and PKCE, which proves the sign-in is finished by the same program that started it, using a fresh random secret made for each sign-in instead of a stored password. The dashboard can show a client secret: leave it hidden, never copy it anywhere and never put it in `.env`.

## Before you start

- **Spotify Premium on the account that will own the app.** Since February 2026 Spotify only lets Premium accounts run apps in development mode, which is the mode every new app starts in. If the owner's Premium lapses later, the app stops working until it is renewed.
- **A verified email address on that Spotify account.** The dashboard won't create apps until the email is verified.
- **FairShuffle on your PC**: either the repo cloned with `uv sync` done, as in the [README](../README.md#developer-setup), or the FairShuffle folder unzipped from a release.
- **A web browser** signed in to that Spotify account.

## 1. Create the app

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and log in with your Spotify account. Accept the Developer Terms if you are asked.
2. Click **Create app** and fill in the form:

   | Field | What to enter |
   |-------|---------------|
   | App name | 2 to 64 characters, **without the word "Spotify"** and **not starting with "Spot"**, for example `FairShuffle Dev`. Spotify's rules don't allow names that use or sound like its brand; "for Spotify" at the end is allowed. |
   | App description | Required, 2 to 256 characters: `Reorders my own playlists with a true random shuffle.` |
   | Select an organization for this app | Only shown if your account belongs to an organization. Pick **Personal**. |
   | Website | Optional. The repo URL is fine. |
   | Redirect URIs | `http://127.0.0.1:8888/callback`, typed exactly like that, then click **Add** (or press Enter). Keep the port: the form refuses an `http` address without one. |
   | Which API/SDKs are you planning to use? | Tick **Web API** only. |

3. Tick the box to agree to Spotify's terms and click **Save**.

### Why the Redirect URI looks like that

After you approve the sign-in in your browser, Spotify sends the browser back to the Redirect URI with a one-time code. FairShuffle runs a tiny web listener on your own PC to catch it, so the address must point at your PC:

- `127.0.0.1` is the loopback address: traffic to it never leaves your PC, like a loopback interface on a router. Spotify **does not allow the word `localhost`** here, only the IP address.
- `8888` is the port the listener uses. Plain `http` is fine because the traffic never leaves the machine; Spotify only allows `http` for loopback addresses.
- `/callback` is the path the listener answers on.

The value must match `SPOTIFY_REDIRECT_URI` in your `.env` character for character, or Spotify refuses the sign-in.

## 2. Copy the Client ID into `.env`

1. After **Save**, the dashboard opens your app's **Basic Information** page (later, open it from the dashboard's app list). It shows the **Client ID** with a copy button. Do not click "View client secret"; FairShuffle never needs it. The Client ID also appears in the browser's address bar (`/dashboard/<Client ID>`), so keep that out of screenshots too.
2. In PowerShell, in the project folder, make your own `.env` from the template:

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

3. Replace `your-client-id-here` with your Client ID. Leave `SPOTIFY_REDIRECT_URI` as `http://127.0.0.1:8888/callback`. Save and close Notepad.

`.env` is listed in `.gitignore`, so Git never commits it, and Claude Code's settings block its file tools from reading it. Keep your Client ID out of commits, issues, pull requests, screenshots and chat. It is not a password, but it is tied to your Spotify account and to your app's user limit, so the project treats it as private (Rule 2 in `CLAUDE.md`).

## 3. Check who can sign in

An app in development mode works for at most five Spotify accounts, and only the ones listed on its **User Management** page (the page shows an "n/5 added" counter). Someone who isn't listed may still get through the sign-in page, but Spotify then refuses FairShuffle's requests with access denied (403).

Spotify's docs don't say whether the app's owner has to be on the list. You can add yourself now to be safe, which uses one of the five places, or wait and add yourself only if FairShuffle reports access denied. To add someone, open **User Management**, fill in **Full Name** and the **Email** of their Spotify account and click **Add user**. Add a friend the same way if you want them to try FairShuffle.

## 4. Make a test playlist (for later)

Before FairShuffle ever writes to a real playlist (milestone M4), it runs on a throwaway one. Whenever you have a minute, create a playlist called **Shuffle Test** with about 30 songs you don't mind seeing reordered. Sign-in (M2) and listing playlists (M3) only read from Spotify, so nothing changes until then.

## 5. Sign in once more for the player (v0.6.0 and later)

True Shuffle (the tick box in the tray menu) controls playback in your Spotify app, which needs two more permissions than shuffling a playlist: `user-read-playback-state` (see what is playing and on which device) and `user-modify-playback-state` (play, pause, skip and turn Spotify's shuffle off). A sign-in saved by v0.5.0 or older doesn't have them, so FairShuffle says once at start that it needs one more sign-in, and the tray menu shows **Allow playback control…**. Pick it, approve FairShuffle in the browser and you are done. Nothing changes on the dashboard, and Shuffle and Undo keep working in the meantime. If you close the tab or cancel instead, FairShuffle picks your earlier sign-in back up.

## If something goes wrong

| What you see | Likely cause | Fix |
|--------------|--------------|-----|
| "Insecure redirect URI" or "This redirect URI is not secure" in the Create app form | The address uses `localhost`, or is `http` without a port | Type `http://127.0.0.1:8888/callback` exactly |
| A Spotify error page about the redirect URI when you sign in | The Redirect URI in the dashboard and `SPOTIFY_REDIRECT_URI` in `.env` differ (often a missing `/callback`, a trailing slash or another port) | Make both read `http://127.0.0.1:8888/callback` exactly |
| A Spotify error page about the client when you sign in | The Client ID in `.env` is wrong or has extra spaces | Copy it again from the app's Basic Information page |
| FairShuffle starts with "SPOTIFY_CLIENT_ID is not set" | `.env` is missing, or still has `your-client-id-here` | Do step 2 again |
| Sign-in works, but FairShuffle reports access denied (403) | Your account isn't on the app's User Management list | Add it, as in step 3 |
| The form shows "Upgrade to Spotify Premium to access the Web API" and **Web API** can't be ticked | The owner account doesn't have Premium | Use a Premium account to own the app |
| An app that used to work stops working | The owner's Premium lapsed | Renew it; the app works again once it is active |

Spotify doesn't document the exact wording of its sign-in error pages, so the two "error page" rows describe them rather than quote them.

## What lives where

| Value | Where it is kept | In Git? |
|-------|------------------|---------|
| Client ID | `.env` in your project folder, or next to `FairShuffle.exe` for the built app | Never |
| Redirect URI | `.env`, and the app's Basic Information page in the dashboard | `.env.example` holds the standard one |
| Client secret | Nowhere. Not used | Never |
| Sign-in tokens (M2) | Windows Credential Manager and the app's memory, never a file FairShuffle writes | Never |

The facts in this guide come from the project's checks of Spotify's developer docs (see `.claude/skills/spotify-api-notes/SKILL.md` for the dates). If the dashboard looks different from what is written here, say so in an issue so the guide can be updated.
