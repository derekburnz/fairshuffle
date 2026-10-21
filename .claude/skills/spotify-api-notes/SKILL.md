---
name: spotify-api-notes
description: Verified, dated facts about the current Spotify Web API for this project (2026 development mode rules, renamed playlist endpoints, PKCE sign-in, loopback redirect URIs, paging limits, rate limits, refresh token expiry). Use before writing, reviewing or debugging any code that calls Spotify.
---

# Spotify Web API notes

Last verified: 2026-10-21 (no Web API changes since the July 2026 changelog; wording fixes from the #11 re-check). If this date is more than about a month old, or a request behaves unexpectedly, ask the `spotify-api-researcher` agent to re-check and update this file. The changelog navigation lists only the February, March, May and July 2026 changelogs; the newest blog post (Aug 13, 2026, Spotify Soloist) is not a Web API change.

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
| User's playlists | `GET /v1/me/playlists` | Returns owned and followed playlists; filter by `owner.id` or `collaborative`. `limit` max 50 (default 20), `offset` max 100,000. Use `items.total`; `tracks.total` is deprecated. `GET /users/{id}/playlists` was removed. |
| Playlist items | `GET /v1/playlists/{id}/items` | Max `limit` 50 (default 20). Owned or collaborative playlists only, else 403. Each entry's item is under `item` (`track` is deprecated). The page's `fields` examples still use the old `track(...)` names. |
| Reorder items | `PUT /v1/playlists/{id}/items` | Body: `range_start`, `insert_before`, `range_length` (default 1), `snapshot_id`. Returns new `snapshot_id`. Scopes `playlist-modify-public` and `playlist-modify-private`. |
| Replace items | `PUT /v1/playlists/{id}/items` | Body: `uris` (max 100). Cannot be combined with reorder in one request. |
| Add items | `POST /v1/playlists/{id}/items` | Max 100 URIs per request. |
| Create playlist | `POST /v1/me/playlists` | Replaces `POST /users/{id}/playlists`. |
| Liked Songs (read) | `GET /v1/me/tracks` | Backlog only. Max 50 per page. Needs extra scope `user-library-read`. The Feb 2026 changelog lists `GET /me/tracks` as still available (only `PUT` and `DELETE /me/tracks` and `GET /me/tracks/contains` were removed). Save and remove moved to `PUT` and `DELETE /v1/me/library`. The reference page was last read Sept 24, 2026. |

Old paths: the `/playlists/{id}/tracks` paths (GET, POST, PUT, DELETE) are REMOVED for development mode apps created on or after Feb 11, 2026 (Feb 2026 changelog and migration guide). Their reference pages still show them as DEPRECATED, and they keep working for extended quota apps and for older development mode apps whose endpoint changes were postponed on Mar 9, 2026. The docs do not say what status a removed path returns. Never call them; use `/items`.

Response shape change: playlist objects use `items` where they used to use `tracks`, and `items.items[].item` where they used to use `tracks.items[].track`.

## Rate limits

- Rolling 30-second window. Over the limit: HTTP 429 with a `Retry-After` header (seconds) that is "normally" present. Wait that long, then retry; use a fallback backoff when the header is missing.
- Since July 2026, quota overruns return 429 with a JSON body containing `"reason": "QUOTA_EXCEEDED"` (the Regular Error Object's optional `reason` field). Now also on the Quota modes and API calls pages.
- Numeric limits are not published. Pace requests, count them and back off.
- Use `snapshot_id` to avoid refetching unchanged playlists.
- The rate limits page still recommends batch endpoints such as "Get Multiple Albums", which were removed in Feb 2026, so that page is stale.

## Known limits

- Liked Songs is not a playlist and cannot be reordered.
- Local files: the Web API cannot add them to a playlist, only reorder and remove them (Spotify "Playlists" concept page, re-read Oct 21, 2026). Reorder keeps them; replace or add loses them. In `GET .../items` they have `is_local: true` and a `spotify:local:...` URI.
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
- https://developer.spotify.com/documentation/web-api/reference/get-playlists-items
- https://developer.spotify.com/documentation/web-api/reference/get-users-saved-tracks
