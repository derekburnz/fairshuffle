---
name: spotify-api-notes
description: Verified, dated facts about the current Spotify Web API for this project (2026 development mode rules, renamed playlist endpoints, PKCE sign-in, loopback redirect URIs, paging limits, rate limits, refresh token expiry). Use before writing, reviewing or debugging any code that calls Spotify.
---

# Spotify Web API notes

Last verified: 2026-09-24. If this date is more than about a month old, or a request behaves unexpectedly, ask the `spotify-api-researcher` agent to re-check and update this file.

## Account and app rules (development mode)

- App owner must have Spotify Premium (since Feb 11, 2026 for new apps, Mar 9, 2026 for existing apps).
- Max 5 authorized users per app. Up to 25 Client IDs per developer (since July 2026); quotas are shared per developer account.
- Extended quota is not available to individuals (organizations only since May 15, 2025, with at least 250,000 monthly active users). The rate limits page still says "any developer can request"; the quota modes page is the stricter and newer rule.
- The Feb 6, 2026 blog says new integrations get a smaller endpoint set. Every endpoint in the table below is listed as still available in the Feb 2026 changelog.

## Sign-in (Authorization Code with PKCE)

- No client secret. Never create or use one.
- Authorize: `GET https://accounts.spotify.com/authorize` with `client_id`, `response_type=code`, `redirect_uri`, `code_challenge_method=S256`, `code_challenge`, `state`, `scope`.
- Token: `POST https://accounts.spotify.com/api/token` (form-encoded) with `grant_type=authorization_code`, `code`, `redirect_uri`, `client_id`, `code_verifier`.
- Refresh: same endpoint with `grant_type=refresh_token`, `refresh_token`, `client_id`. The response may or may not include a new refresh token; if not, keep the old one.
- Access tokens last about 1 hour.
- Refresh tokens expire 6 months after the original authorization. Refreshing does not extend this. Expired: `400` with `invalid_grant`. Do not retry; delete the stored token and ask the user to sign in again.
- Redirect URI: `localhost` is NOT allowed. Use `http://127.0.0.1:PORT/callback` or `http://[::1]:PORT/callback`. HTTP is only allowed for loopback. A loopback URI can be registered without a port and the port added at request time.
- Scopes for this app: `playlist-read-private`, `playlist-read-collaborative`, `playlist-modify-private`, `playlist-modify-public`.

## Endpoints we use

| Purpose | Method and path | Notes |
|---------|-----------------|-------|
| Current user | `GET /v1/me` | `email`, `country`, `product` fields were removed in 2026. New `account_id` field (May 2026) is the stable ID to prefer. |
| User's playlists | `GET /v1/me/playlists` | Paged. `GET /users/{id}/playlists` was removed. |
| Playlist items | `GET /v1/playlists/{id}/items` | Max `limit` 50 (default 20). Owned or collaborative playlists only, else 403. Old `/tracks` path returns 403. |
| Reorder items | `PUT /v1/playlists/{id}/items` | Body: `range_start`, `insert_before`, `range_length` (default 1), `snapshot_id`. Returns new `snapshot_id`. |
| Replace items | `PUT /v1/playlists/{id}/items` | Body: `uris` (max 100). Cannot be combined with reorder in one request. |
| Add items | `POST /v1/playlists/{id}/items` | Max 100 URIs per request. |
| Create playlist | `POST /v1/me/playlists` | Replaces `POST /users/{id}/playlists`. |
| Liked Songs (read) | `GET /v1/me/tracks` | Backlog only. Max 50 per page. Needs extra scope `user-library-read`. Still documented (Sept 2026), but the Feb 2026 changelog contradicts itself about it, so re-check first. Save and remove moved to `PUT` and `DELETE /v1/me/library`. |

Response shape change: playlist objects use `items` where they used to use `tracks`, and `items.items[].item` where they used to use `tracks.items[].track`.

## Rate limits

- Rolling 30-second window. Over the limit: HTTP 429 with a `Retry-After` header (seconds). Wait that long, then retry.
- Since July 2026, quota overruns return 429 with a JSON body containing `"reason": "QUOTA_EXCEEDED"`.
- Numeric limits are not published. Pace requests, count them and back off.
- Use `snapshot_id` to avoid refetching unchanged playlists.

## Known limits

- Liked Songs is not a playlist and cannot be reordered.
- Local files: the Web API cannot add them to a playlist, only reorder and remove them (confirmed Sept 24, 2026, Spotify "Playlists" concept page). Reorder keeps them; replace or add loses them. In `GET .../items` they have `is_local: true` and a `spotify:local:...` URI.
- Episodes: `item.type` is `"episode"`. They can be reordered, replaced and added like tracks.

## Sources

- https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide
- https://developer.spotify.com/documentation/web-api/references/changes/july-2026
- https://developer.spotify.com/documentation/web-api/references/changes/may-2026
- https://developer.spotify.com/blog/2026-06-18-refresh-token-expiration
- https://developer.spotify.com/documentation/web-api/reference/reorder-or-replace-playlists-items
- https://developer.spotify.com/documentation/web-api/reference/get-playlists-items
- https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow
- https://developer.spotify.com/documentation/web-api/concepts/redirect_uri
- https://developer.spotify.com/documentation/web-api/concepts/rate-limits
- https://developer.spotify.com/documentation/web-api/concepts/quota-modes
- https://developer.spotify.com/documentation/web-api/concepts/playlists
- https://developer.spotify.com/documentation/web-api/reference/get-users-saved-tracks
