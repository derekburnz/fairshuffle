"""True shuffle: play a playlist in a fair random order in the user's own Spotify app, without
changing the playlist (M6, P6-04).

Spotify's shuffle button picks its own order. FairShuffle instead deals a Fisher-Yates order
(engine.py), writes it into one private playlist of its own, "FairShuffle: True Shuffle", turns
Spotify's shuffle off and starts that playlist from track 1 (P6-01a). The Spotify app then
plays our order like any playlist: Next and Previous follow it, and it carries on with
FairShuffle closed to the tray. The networking picture: FairShuffle builds the route (the
order) and installs it once; the Spotify app forwards along it on its own.

The playlist the user picked is only read. Local files and songs Spotify no longer has can't
be added to a playlist through the Web API, so they are left out of the order, and the result
says how many.

Spotify says "The order of execution is not guaranteed when you use this API with other Player
API endpoints", so after "shuffle off, then play" the state is read back, and the commands are
sent again (a few times, with short waits) until Spotify reports shuffle off, our playlist
playing and our first song on. Every step runs on a worker thread.

Song URIs, playlist IDs and device names are the user's data: counts only in the log.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from random import Random

from fairshuffle.shuffle.engine import shuffled
from fairshuffle.shuffle.planner import Append, Replace, uri_plan, writable_uris
from fairshuffle.shuffle.verify import verify
from fairshuffle.spotify import player
from fairshuffle.spotify.client import SpotifyClient
from fairshuffle.spotify.errors import NotOwner, RequestRejected, SpotifyError
from fairshuffle.spotify.models import Playlist
from fairshuffle.spotify.playlists import create_private_playlist, read_playlist_items

PLAYLIST_NAME = "FairShuffle: True Shuffle"
PLAYLIST_DESCRIPTION = (
    "Made by FairShuffle to play a true shuffle. FairShuffle rewrites it each time you turn True "
    "Shuffle on; your own playlists are never changed."
)
CHECKS = 4  # reads of the player state after "shuffle off, then play"
CHECK_WAITS = (0.5, 1.0, 2.0)  # seconds between them
READ_BACK_WAIT = 1.0  # Spotify's reads can lag a write for about a second (#31)

log = logging.getLogger(__name__)


class NothingToPlay(SpotifyError):
    """The playlist has no song the Web API can play: it is empty, or only local files."""


@dataclass(frozen=True)
class Session:
    """A true shuffle that is playing, as start() left it. stop() needs it to go back."""

    playlist: Playlist = field(repr=False)  # the one the user picked
    play_playlist_id: str = field(repr=False)  # FairShuffle's own, holding the order
    order: tuple[str, ...] = field(repr=False)
    original: tuple[str | None, ...] = field(repr=False)  # the picked playlist's items, in order
    skipped: int  # local files and unavailable songs left out of the order
    shuffle_was_on: bool  # Spotify's own shuffle before, put back by stop()
    device_id: str | None = field(repr=False)
    confirmed: bool  # Spotify reported our order playing before start() returned

    @property
    def play_uri(self) -> str:
        return f"spotify:playlist:{self.play_playlist_id}"


def start(
    client: SpotifyClient,
    playlist: Playlist,
    play_playlist_id: str | None,
    rng: Random | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Session:
    """Deal a fair order for playlist and start it in the user's Spotify app.

    play_playlist_id is FairShuffle's own playlist from an earlier run (the settings keep it), or
    None; a new one is made when there is none or it is gone. Raises NoActiveDevice,
    DeviceRestricted, PremiumRequired, NothingToPlay or another SpotifyError.
    """
    device = player.controllable_device(client)  # before any write, so a closed app costs nothing
    state = player.playback_state(client)
    items = read_playlist_items(client, playlist.id)
    playable = writable_uris(items)
    if not playable:
        raise NothingToPlay(
            "This playlist has no songs FairShuffle can play. Local files can't be played this way."
        )
    order = shuffled(playable, rng)
    target = _write_order(client, play_playlist_id, order, sleep)
    session = Session(
        playlist=playlist,
        play_playlist_id=target,
        order=tuple(order),
        original=tuple(item.uri for item in items),
        skipped=len(items) - len(playable),
        shuffle_was_on=state.shuffle if state is not None else False,
        device_id=device.id,
        confirmed=False,
    )
    confirmed = _play_and_confirm(client, session, sleep)
    log.info(
        "True shuffle started: %d songs, %d left out, confirmed %s",
        len(order),
        session.skipped,
        confirmed,
    )
    return replace(session, confirmed=confirmed)


def stop(client: SpotifyClient, session: Session) -> bool:
    """Go back to normal play: Spotify's shuffle as it was, and the picked playlist playing from
    the song that is on now. Returns False, and changes nothing, when the user has already moved
    on to something else in Spotify, since the toggle shouldn't take that away from them.
    """
    state = player.playback_state(client)
    if state is None or state.context_uri != session.play_uri:
        log.info("True shuffle turned off after playback had moved on; nothing to change")
        return False
    current = state.item.uri if state.item is not None else None
    offset = session.original.index(current) if current in session.original else 0
    device_id = session.device_id if state.device is None else state.device.id
    player.set_shuffle(client, session.shuffle_was_on, device_id)
    player.play(
        client,
        context_uri=f"spotify:playlist:{session.playlist.id}",
        offset=offset,
        device_id=device_id,
    )
    if not state.is_playing:
        player.pause(client, device_id)
    log.info("True shuffle off; back to the playlist")
    return True


def _write_order(
    client: SpotifyClient,
    play_playlist_id: str | None,
    order: Sequence[str],
    sleep: Callable[[float], None],
) -> str:
    """Write order into FairShuffle's own playlist, making it first if needed. Returns its ID."""
    target = play_playlist_id
    plan = uri_plan(order)
    if target is not None:
        try:
            _send(client, target, plan[0])
        except NotOwner, RequestRejected:  # deleted, or no longer the user's: make a new one
            log.info("The true shuffle playlist is gone; making a new one")
            target = None
    if target is None:
        target = create_private_playlist(client, PLAYLIST_NAME, PLAYLIST_DESCRIPTION)
        _send(client, target, plan[0])
    for write in plan[1:]:
        _send(client, target, write)
    verdict = verify(order, read_playlist_items(client, target))
    if not verdict.ok:  # reads can lag a write (#31): one more look before giving up
        sleep(READ_BACK_WAIT)
        verdict = verify(order, read_playlist_items(client, target))
    if not verdict.ok:
        raise SpotifyError("Spotify didn't take the shuffled order. Try again.")
    return target


def _send(client: SpotifyClient, playlist_id: str, write: Replace | Append) -> None:
    path = f"/playlists/{playlist_id}/items"
    uris = list(write.uris)
    if isinstance(write, Replace):
        client.put(path, {"uris": uris})
    else:
        client.post(path, {"uris": uris})


def _play_and_confirm(
    client: SpotifyClient, session: Session, sleep: Callable[[float], None]
) -> bool:
    """Shuffle off, play our playlist from track 1, then read back until Spotify agrees."""
    device_id = session.device_id
    player.set_shuffle(client, False, device_id)
    player.play(client, context_uri=session.play_uri, offset=0, device_id=device_id)
    for check in range(CHECKS):
        state = player.playback_state(client)
        if state is not None and _is_ours(state, session):
            return True
        if check == CHECKS - 1:
            break
        sleep(CHECK_WAITS[min(check, len(CHECK_WAITS) - 1)])
        # Shuffle still on, the play not landed, or it landed before the shuffle-off and so
        # started on Spotify's pick of song: send what is missing and start from track 1 again.
        if state is not None and state.shuffle:
            player.set_shuffle(client, False, device_id)
        player.play(client, context_uri=session.play_uri, offset=0, device_id=device_id)
    log.warning("Spotify didn't confirm the true shuffle order in time")
    return False


def _is_ours(state: player.PlaybackState, session: Session) -> bool:
    playing = state.item.uri if state.item is not None else None
    return (
        not state.shuffle and state.context_uri == session.play_uri and playing == session.order[0]
    )
