---
name: spotify-api-notes
description: Verified, dated facts about the current Spotify Web API for this project (2026 development mode rules, renamed playlist endpoints, PKCE sign-in, loopback redirect URIs, paging limits, rate limits, refresh token expiry). Use before writing, reviewing or debugging any code that calls Spotify.
---

# Spotify Web API notes

Last verified: 2026-10-21 (Phase 4 re-check of the write endpoints: `PUT` and `POST /playlists/{id}/items` and the Playlists concept page; earlier the same day the Phase 3 re-check of `/me/playlists`, `/playlists/{id}/items` and `/playlists/{id}`; no Web API changes since the July 2026 changelog; wording fixes from the #11 re-check). If this date is more than about a month old, or a request behaves unexpectedly, ask the `spotify-api-researcher` agent to re-check and update this file. The changelog navigation lists only the February, March, May and July 2026 changelogs (the June to October 2026 change pages return 404); the newest blog post (Aug 13, 2026, Spotify Soloist) is not a Web API change.

## Account and app rules (development mode)

- App owner must have Spotify Premium (since Feb 11, 2026 for new apps, Mar 9, 2026 for existing apps). If the owner's Premium lapses, the app stops working until they resubscribe. The docs require Premium only for the owner.
- Max 5 authorized users per app, added under the dashboard's User Management tab. Up to 25 Client IDs per developer (since July 2026); quotas are shared per developer account.
- Users not on the list may still be able to sign in, but API calls with their token return 403 (body not documented). The docs do not say whether the owner must add themselves.
- Extended quota is not available to individuals (organizations only since May 15, 2025, with at least 250,000 monthly active users). The rate limits page still says "any developer can request"; the quota modes page is the stricter and newer rule.
- The Feb 6, 2026 blog says new integrations get a smaller endpoint set. Every endpoint in the table below is listed as still available in the Feb 2026 changelog.

## Sign-in (Authorization Code with PKCE)

- No client secret. Never create or use one.
- Authorize: `GET https://accounts.spotify.com/authorize` with `client_id`, `response_type=code`, `redirect_uri`, `code_challenge_method=S256`, `code_challenge`, `state`, `scope`. The callback returns `code` and `state`, or `error` (for example `access_denied`) and `state`.
- Code verifier is 43 to 128 characters (letters, digits, `_ . - ~`); the challenge is base64url SHA-256 without padding.
- Token: `POST https://accounts.spotify.com/api/token` with `grant_type=authorization_code`, `code`, `redirect_uri` (must exactly match the authorize request), `client_id`, `code_verifier`.
- Refresh: same endpoint with `grant_type=refresh_token`, `refresh_token`, `client_id`. The response may or may not include a new refresh token; if not, keep the old one.
- Token requests use `Content-Type: application/x-www-form-urlencoded`. With PKCE there is no Authorization header and `client_id` goes in the body.
- Access tokens last about 1 hour (`expires_in` 3600).
- Refresh tokens expire 6 months after the original authorization. Refreshing does not extend this. Expired, revoked or otherwise invalid: `400` with `invalid_grant` (sample body has only `error`). Do not retry; delete the stored token and ask the user to sign in again.
- Refresh tokens carry no issue time. Store the original sign-in time to warn before 6 months. The dashboard shows a "Refresh Token Lifetime" field.
- Token endpoint errors use the OAuth error object (`error`, `error_description`). Errors for a bad code, verifier or `redirect_uri` are not documented; treat any 400 from the code exchange as a failed sign-in and do not retry.
- Redirect URI: `localhost` is NOT allowed. Use `http://127.0.0.1:PORT/callback` or `http://[::1]:PORT/callback`. HTTP is only allowed for loopback. Matching is exact (case, trailing slash), except that a loopback port may change.
- The docs allow registering a loopback URI without a port, but the dashboard's Create app form rejects `http` URIs without an explicit port ("Insecure redirect URI"). Register `http://127.0.0.1:8888/callback` with the port.
- The error Spotify shows for a redirect URI that doesn't match is not documented.
- Scopes for this app: `playlist-read-private`, `playlist-read-collaborative`, `playlist-modify-private`, `playlist-modify-public` and `user-read-private` (P2-4, for the `/me` display name). The scopes page (read 2026-10-21) lists `user-read-private` as "Read access to user's subscription details", shown to the user as "Access your subscription details", with Search and Get Current User's Profile as the endpoints that need it. Never ask for `user-read-email`.

## Endpoints we use

| Purpose | Method and path | Notes |
|---------|-----------------|-------|
| Current user | `GET /v1/me` | Fields: `account_id` (the stable ID to prefer for linking, May 2026), `display_name` (may be `null`), `id`, `images`, `uri`. `country`, `email`, `explicit_content`, `followers`, `product` are removed for development mode (changelog) and shown as Deprecated on the reference page. The docs list `user-read-private` and `user-read-email` as scopes for `/me` and do not say whether `id` or `display_name` come back with the playlist scopes only, so FairShuffle asks for `user-read-private` too (P2-4, 2026-10-21). |
| User's playlists | `GET /v1/me/playlists` | Returns owned and followed playlists; filter by `owner.id` or `collaborative`. `limit` max 50 (default 20), `offset` max 100,000. Use `items.total`; `tracks.total` is deprecated. `GET /users/{id}/playlists` was removed. The reference page lists only `playlist-read-private`; the Playlists concept page says collaborative playlists come back only with `playlist-read-collaborative` and private ones only with `playlist-read-private`, and also says "excluding collaborative playlists owned by other users", which conflicts with its own scope list, so rely on neither. Paging object: `href`, `limit`, `next` (null on the last page), `offset`, `previous`, `total`, `items`. Each playlist has `id`, `name`, `owner.id`, `owner.display_name` (nullable), `collaborative`, `public`, `snapshot_id`, `items.total`, `images`, `uri`. Treat `items.total` as optional (Feb 2026: only owned playlists return an items object). Image URLs expire in less than a day; never cache them. |
| Playlist items | `GET /v1/playlists/{id}/items` | Max `limit` 50 (default 20). Owned or collaborative playlists only, else 403. Each entry's item is under `item` (`track` is deprecated). The page's `fields` examples still use the old `track(...)` names, and none uses `item(...)`; check the new names against a recorded fixture before relying on `fields`. No maximum `offset` documented. Always send `additional_types=track,episode` and check `item.type`; the docs do not say what episodes look like without it. `market` is optional (the token's country wins). `added_at` and `added_by` may be null on very old playlists. Treat `item: null` as possible (the playlist object docs say an item may be null when no longer available; the items page does not). Unavailable tracks may carry `restrictions.reason` (`market`, `product`, `explicit`). Track `linked_from` is REMOVED for development mode (Feb 2026); never read it. Scope listed: `playlist-read-private` only. |
| Single playlist | `GET /v1/playlists/{id}` | Metadata plus `snapshot_id`; `items` as a paging object (first page plus `items.total`) only for playlists the user owns or collaborates on, metadata only for others (Feb 2026 changelog). No scopes listed. Its `fields` examples still use `tracks.items(...)`. For a `snapshot_id` cache, `GET /me/playlists` already carries `snapshot_id` and `items.total` per playlist. |
| Reorder items | `PUT /v1/playlists/{id}/items` | Body: `range_start`, `insert_before`, `range_length` (defaults to 1, no documented maximum), `snapshot_id`. `200` with `{"snapshot_id": ...}`; other codes listed are 401, 403 and 429. Scopes `playlist-modify-public` and `playlist-modify-private`. "Replace and reorder are mutually exclusive operations which share the same endpoint ... can't be applied together in a single request." |
| Replace items | `PUT /v1/playlists/{id}/items` | `uris` as a query parameter or in the body; track or episode URIs. "A maximum of 100 items can be set in one request" is stated on the query parameter only (the body array shows no maximum), so send at most 100. Replacing "will overwrite its existing items" and "can be used for replacing or clearing". `200` with `snapshot_id`. Not documented: whether `snapshot_id` is honoured, ignored or refused on replace; whether `uris: []` is how to clear; which `uris` wins if sent both ways. Send `uris` in the body only. |
| Add items | `POST /v1/playlists/{id}/items` | `uris` in the query or the body, max 100 per request, track or episode URIs; "if the uris parameter is present in the query string, any URIs listed here in the body will be ignored", and long lists belong in the body. Optional zero-based `position` (query or body); left out, items are appended, in array order. `201` with `snapshot_id`. Same scopes. |
| Create playlist | `POST /v1/me/playlists` | Replaces `POST /users/{id}/playlists`. |
| Liked Songs (read) | `GET /v1/me/tracks` | Backlog only. Max 50 per page. Needs extra scope `user-library-read`. The Feb 2026 changelog lists `GET /me/tracks` as still available (only `PUT` and `DELETE /me/tracks` and `GET /me/tracks/contains` were removed). Save and remove moved to `PUT` and `DELETE /v1/me/library`. The reference page was last read Sept 24, 2026. |

Old paths: the `/playlists/{id}/tracks` paths (GET, POST, PUT, DELETE) are REMOVED for development mode apps created on or after Feb 11, 2026 (Feb 2026 changelog and migration guide). Their reference pages still show them as DEPRECATED, and they keep working for extended quota apps and for older development mode apps whose endpoint changes were postponed on Mar 9, 2026. The docs do not say what status a removed path returns. Never call them; use `/items`.

Response shape change: playlist objects use `items` where they used to use `tracks`, and `items.items[].item` where they used to use `tracks.items[].track`.

## Player endpoints (planning check for M6 and P6-01 re-check, both 2026-10-25)

First read for the D26 planning cards, then re-checked for P6-01 before `spotify/player.py` was written (#112). The re-check found the pages unchanged and added the points marked "P6-01".

- The Feb 2026 changelog lists every Player endpoint under "Endpoints still available": Start/Resume Playback (`PUT /me/player/play`), Toggle Shuffle (`PUT /me/player/shuffle`), Add Item to Queue (`POST /me/player/queue`), Get User's Queue (`GET /me/player/queue`), Get Playback State (`GET /me/player`), Get Available Devices, Get Currently Playing, Get Recently Played, Transfer Playback, Pause, Seek, Repeat, Volume, Next and Previous. The migration guide says nothing about them.
- Play, shuffle, queue (and the other control endpoints): "This API only works for users who have Spotify Premium." Every user of the player needs Premium, not only the app owner. Control scope: `user-modify-playback-state`. `GET /me/player` needs `user-read-playback-state`; `GET /me/player/queue` lists `user-read-currently-playing` and `user-read-playback-state`.
- `PUT /me/player/play`: optional `device_id` (default: the active device); body `context_uri` (album, artist or playlist) with `offset` (`position` zero-based or `uri`, playlists and albums only), or `uris` (track URIs), plus `position_ms`. `204` on success; 401, 403 and 429 listed without descriptions. No maximum number of `uris` is documented; find the working size by hand (P6-08).
- `PUT /me/player/shuffle`: `state` required (`false` turns shuffle off), optional `device_id`, `204` "Command sent".
- `POST /me/player/queue`: one track or episode `uri` per call, `204`. No endpoint clears the queue.
- Every player page: "The order of execution is not guaranteed when you use this API with other Player API endpoints." Read the state back after a sequence of commands.
- `GET /me/player`: `device` (`id` nullable, `is_active`, `is_restricted` "no Web API commands will be accepted by this device", `name`, `type`), `shuffle_state`, `repeat_state`, `context` (nullable, has `uri`), `item` (nullable), `progress_ms`, `is_playing`, `currently_playing_type` (`track`, `episode`, `ad`, `unknown`). Codes 200, 204, 401, 403, 429; 204 is not described. No `smart_shuffle` field is documented.
- P6-01: the Regular Error Object (concepts/api-calls) documents only `QUOTA_EXCEEDED` as a `reason`. The player reason codes developers see (`NO_ACTIVE_DEVICE` with 404, `PREMIUM_REQUIRED` with 403, "Player command failed: ...") are no longer documented anywhere on developer.spotify.com, so `spotify/player.py` maps them defensively and the live test (#117) records what Spotify actually sends.
- P6-01: `GET /me/player` lists no Premium note; its `actions` object says which commands the current context allows (`toggling_shuffle` among them). `offset` on play is "Only available when context_uri corresponds to an album or playlist object", so a `uris` list always starts at its first entry.
- P6-01, community reports only (not documentation): a `uris` list of about 150 to 180 songs stalled playback for one developer, and another saw ordered `uris` (155 songs, and as few as 3) start on a song other than the first. Treat both as unconfirmed until the live test.
- P6-01: `POST /me/playlists` (the replacement for the removed `POST /users/{user_id}/playlists`) creates a playlist for the signed-in user: `name` required and not unique, `public` defaults to `true` (a private one needs `public: false` and `playlist-modify-private`), `201` with the playlist object. Users are "generally limited to a maximum of 11000 playlists".
- P6-01a (Derek, 2026-10-25): True Shuffle sends its order as a `uris` list, so nothing is added to the library. `shuffle/session.py` caps one play at `MAX_SONGS` (provisional 500) and recognises its own playback by `context` being null with the current song in its list. Neither the limit nor a null `context` for a `uris` play is documented: the live test (#117) confirms both.
- Web Playback SDK: a browser JavaScript library that makes "a local Spotify Connect device in your browser"; Premium only; documented for websites (iframes must allow `encrypted-media`); "must not be used in commercial projects without Spotify's prior written approval". Not used: FairShuffle controls the user's Spotify app instead.
- Developer Policy (effective 15 May 2025): III.11 "Do not build products or services that mimic, or replicate or attempt to replace a core user experience of Spotify"; II.5 "there shall be no playback of Spotify Content without showing relevant cover art and metadata"; VI.2 the name "should not begin with 'Spot' or be confusing in sound or spelling to Spotify". Developer Terms (version 10, 15 May 2025) VII.1.3: no trademark or domain name that includes "Spotify". Design guidelines: the app name must not include "Spotify"; "for Spotify" is acceptable; attribute Spotify content with the Spotify logo or icon and link back with "OPEN SPOTIFY", "PLAY ON SPOTIFY" or "LISTEN ON SPOTIFY".
- Sources: the Feb 2026 changelog and migration guide (below), https://developer.spotify.com/documentation/web-api/reference/create-playlist, https://developer.spotify.com/documentation/web-api/concepts/api-calls, https://developer.spotify.com/documentation/web-api/reference/start-a-users-playback, .../toggle-shuffle-for-users-playback, .../add-to-queue, .../get-queue, .../get-information-about-the-users-current-playback, https://developer.spotify.com/documentation/web-playback-sdk, https://developer.spotify.com/policy, https://developer.spotify.com/terms, https://developer.spotify.com/documentation/design

## Rate limits

- Rolling 30-second window. Over the limit: HTTP 429 with a `Retry-After` header (seconds) that is "normally" present. Wait that long, then retry; use a fallback backoff when the header is missing.
- Since July 2026, quota overruns return 429 with a JSON body containing `"reason": "QUOTA_EXCEEDED"` (the Regular Error Object's optional `reason` field). Now also on the Quota modes and API calls pages.
- Numeric limits are not published. Pace requests, count them and back off.
- Use `snapshot_id` to avoid refetching unchanged playlists.
- Seen live on 2026-10-22 (#31, Derek's "Shuffle Test" playlist): after a run of reorders, the `snapshot_id` from `GET /playlists/{id}` did not equal the one the last reorder's reply returned, though nobody else edited the playlist. Two `GET`s with no write between them did match. So never compare a write reply's `snapshot_id` with a `GET`'s to detect other editors; compare the songs instead (P4-6). Still send the latest reply's `snapshot_id` with each reorder.
- Seen live again on 2026-10-25 (#31): right after a write, two `GET /playlists/{id}` reads about a second apart returned different `snapshot_id`s with no other editor, while 20 reads half a second apart at rest all matched. Reads seem to lag behind writes briefly (eventual consistency; not documented), which may also explain the reply mismatch above. So when two `snapshot_id` reads disagree right after a write, wait about a second and read again before concluding someone else edited.
- The rate limits page still recommends batch endpoints such as "Get Multiple Albums", which were removed in Feb 2026, so that page is stale.

## Known limits

- Liked Songs is not a playlist and cannot be reordered.
- Local files: "It is not currently possible to add local files to playlists using the Web API, but they can be Reordered or Removed" (Spotify "Playlists" concept page, re-read Oct 21, 2026). Reorder keeps them. That replace loses them is our reading (replace overwrites the list and a local file can't be added back); the page says nothing about sending a `spotify:local:` URI to replace or add. In `GET .../items` they have `is_local: true` and a `spotify:local:{artist}:{album_title}:{track_title}:{duration_in_seconds}` URI.
- Writes have no special rate limit (only playlist image upload has a custom one) and no documented 403 body: both write pages give the generic "Bad OAuth request ... re-authenticating the user won't help here" with `error.status` and `error.message`.
- Check by hand before relying on it: what replace does with a local file URI, and replace followed by add on a playlist over 100 items (Derek's "Shuffle Test" playlist only).
- Episodes: `item.type` is `"episode"`. They can be reordered, replaced and added like tracks.

## Sources

- https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide
- https://developer.spotify.com/documentation/web-api/references/changes/february-2026
- https://developer.spotify.com/documentation/web-api/references/changes/march-2026
- https://developer.spotify.com/documentation/web-api/references/changes/may-2026
- https://developer.spotify.com/documentation/web-api/references/changes/july-2026
- https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security
- https://developer.spotify.com/blog/2026-06-18-refresh-token-expiration
- https://developer.spotify.com/blog/2026-07-23-web-api-quota-updates
- https://developer.spotify.com/community (newest post list)
- https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow
- https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens
- https://developer.spotify.com/documentation/web-api/concepts/api-calls
- https://developer.spotify.com/documentation/web-api/concepts/redirect_uri
- https://developer.spotify.com/documentation/web-api/concepts/rate-limits
- https://developer.spotify.com/documentation/web-api/concepts/quota-modes
- https://developer.spotify.com/documentation/web-api/concepts/scopes
- https://developer.spotify.com/documentation/web-api/concepts/playlists
- https://developer.spotify.com/documentation/web-api/reference/get-current-users-profile
- https://developer.spotify.com/documentation/web-api/reference/get-a-list-of-current-users-playlists
- https://developer.spotify.com/documentation/web-api/reference/reorder-or-replace-playlists-items
- https://developer.spotify.com/documentation/web-api/reference/add-items-to-playlist
- https://developer.spotify.com/documentation/web-api/reference/get-playlists-items
- https://developer.spotify.com/documentation/web-api/reference/get-users-saved-tracks
