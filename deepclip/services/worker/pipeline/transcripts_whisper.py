"""Stage 4 last resort — Whisper transcription. FLAGGED OFF BY DEFAULT.

The spec's fallback chain is: manual captions → auto captions → Whisper on
ephemeral audio → skip. This is the third link.

Two hard constraints, both from the master doc:
  1. **Audio is downloaded only for transcription and deleted immediately.**
     Only text and timestamps are ever stored. This is what keeps "embed, don't
     download" (B4) true — a transient decode is not hosting, but a leftover file
     on disk would be.
  2. It costs real money and needs a GPU (~$0.006/min, C8), so it is off unless
     `DEEPCLIP_WHISPER=1`. Roughly 15% of videos lack captions; silently paying
     for all of them would blow the cost model.

The temp file is deleted in a `finally` block so it goes away even on a crash
mid-transcription.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from ..sources.base import Transcript, TranscriptCue

log = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "base")
MAX_DURATION_S = 3600  # a 3-hour stream is not worth transcribing at $0.006/min

# Player clients to try, in order, when a download is refused. YouTube serves the
# same audio through several client APIs and blocks them independently — a 403 on
# the default web client is routinely served fine to the android/ios ones. Trying
# them in order is what turns "this IP is blocked" into "this IP is blocked on one
# client", which is the difference between a dead pipeline and a slow one.
PLAYER_CLIENT_CHAIN = ("android", "ios", "web_safari", "web")


class AudioForbidden(RuntimeError):
    """Every client was refused (HTTP 403 / bot check) for this IP.

    Distinct from "this video has no audio stream": like TranscriptIpBlocked it is
    an infra condition affecting every video, and the fix is a proxy or cookies,
    not a retry.
    """


def audio_proxy_url() -> str | None:
    """The proxy yt-dlp should use, from the same env the caption path reads.

    Both transcript paths get blocked by the same thing (this IP), so they take
    their proxy from the same place — configuring one and not the other is the
    trap that left the audio path exposed when captions were already protected.
    """
    explicit = os.environ.get("DEEPCLIP_YTDLP_PROXY")
    if explicit:
        return explicit
    user = os.environ.get("WEBSHARE_PROXY_USER")
    pw = os.environ.get("WEBSHARE_PROXY_PASS")
    if user and pw:
        host = os.environ.get("WEBSHARE_PROXY_HOST", "p.webshare.io:80")
        return f"http://{user}:{pw}@{host}"
    return os.environ.get("YTT_PROXY_HTTPS") or os.environ.get("YTT_PROXY_HTTP") or None


def whisper_enabled() -> bool:
    return os.environ.get("DEEPCLIP_WHISPER", "").lower() in {"1", "true", "yes"}


class WhisperUnavailable(RuntimeError):
    pass


def estimate_cost_usd(duration_s: int, rate_per_min: float = 0.006) -> float:
    return max(duration_s, 0) / 60.0 * rate_per_min


_REFUSAL_MARKERS = (
    "http error 403",
    "forbidden",
    "sign in to confirm",
    "not a bot",
    "unable to download api page",
    "failed to extract any player response",
    "requested format is not available",
)


def _is_refusal(exc: Exception) -> bool:
    """Is this yt-dlp failure a block, rather than a broken video?

    A block is worth retrying on another client; a private/deleted video is not,
    so it must propagate instead of burning the whole chain on every video.
    """
    msg = str(exc).lower()
    if any(m in msg for m in ("private video", "video unavailable", "removed by the uploader")):
        return False
    return any(m in msg for m in _REFUSAL_MARKERS)


class WhisperTranscriber:
    """faster-whisper over ephemeral audio.

    The model is loaded lazily and reused: loading large-v3 costs seconds and
    gigabytes, so constructing one per video would dominate the run.
    """

    def __init__(self, model_size: str = DEFAULT_MODEL, device: str | None = None):
        self.model_size = model_size
        # Default to CPU/int8: it runs everywhere (no CUDA needed) and is what a
        # laptop actually has. float16 is GPU-only and crashes on CPU, so only a
        # caller that knows it has a GPU should pass device="cuda".
        self.device = device or os.environ.get("WHISPER_DEVICE", "cpu")
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover
            raise WhisperUnavailable(
                "faster-whisper is not installed; add it to requirements to "
                "enable the Whisper fallback"
            ) from exc
        compute = "float16" if self.device == "cuda" else "int8"
        self._model = WhisperModel(self.model_size, device=self.device, compute_type=compute)
        return self._model

    def transcribe(
        self, video_id: str, max_duration_s: int = MAX_DURATION_S
    ) -> Transcript | None:
        """Download audio, transcribe, delete audio. Returns None if unavailable."""
        if not whisper_enabled():
            log.debug("whisper fallback disabled (DEEPCLIP_WHISPER unset)")
            return None

        workdir = tempfile.mkdtemp(prefix="deepclip-audio-")
        try:
            audio_path = self._download_audio(video_id, workdir, max_duration_s)
            if audio_path is None:
                return None
            return self._transcribe_file(audio_path, video_id)
        except (WhisperUnavailable, AudioForbidden):
            # A blocked audio endpoint affects every video, so it must reach the
            # caller as itself — swallowing it as None reports "no transcript
            # anywhere", the same misleading message TranscriptIpBlocked exists
            # to prevent.
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("whisper failed for %s: %s", video_id, exc)
            return None
        finally:
            # Deleted even on crash. Leaving audio on disk would turn a transient
            # decode into hosting, which is the line the architecture rests on.
            shutil.rmtree(workdir, ignore_errors=True)
            if Path(workdir).exists():  # pragma: no cover
                log.error("FAILED TO DELETE AUDIO WORKDIR %s", workdir)

    @staticmethod
    def _download_audio(video_id: str, workdir: str, max_duration_s: int) -> str | None:
        """Audio-only fetch via yt-dlp. Never video, never retained.

        Deliberately does NOT run the FFmpegExtractAudio postprocessor: that needs
        a system ffmpeg, and faster-whisper decodes the raw m4a/webm directly via
        its bundled PyAV. Skipping it removes the ffmpeg dependency entirely.

        Crucially, audio comes from googlevideo.com, a different host than the
        caption endpoint YouTube IP-blocks under load — so this path keeps working
        when youtube-transcript-api is blocked, which is the whole reason it exists.
        """
        try:
            import yt_dlp
        except ImportError as exc:  # pragma: no cover
            raise WhisperUnavailable("yt-dlp is not installed") from exc

        url = f"https://www.youtube.com/watch?v={video_id}"
        out = os.path.join(workdir, "%(id)s.%(ext)s")
        proxy = audio_proxy_url()
        cookies = os.environ.get("YTDLP_COOKIES_FILE")
        base = {
            # worstaudio keeps the file small; Whisper does not need fidelity.
            "format": "worstaudio/bestaudio/best",
            "outtmpl": out,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            # Progress bars are carriage-return spam in a worker log, where they
            # bury the lines that matter (which client answered, which video).
            "noprogress": True,
            # A refused fetch is not worth ten retries against the same block;
            # switching client is what actually helps, so fail over fast.
            "retries": 1,
            "fragment_retries": 1,
        }
        if proxy:
            base["proxy"] = proxy
        if cookies:
            base["cookiefile"] = cookies

        refusals = []
        for client in PLAYER_CLIENT_CHAIN:
            opts = dict(base, extractor_args={"youtube": {"player_client": [client]}})
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    duration = int(info.get("duration") or 0)
                    if duration > max_duration_s:
                        log.info(
                            "skipping whisper for %s: %ds exceeds %ds cap (~$%.2f)",
                            video_id, duration, max_duration_s,
                            estimate_cost_usd(duration),
                        )
                        return None
                    ydl.download([url])
            except Exception as exc:  # noqa: BLE001 - yt-dlp raises many types
                if not _is_refusal(exc):
                    raise
                refusals.append(f"{client}: {exc}")
                log.info("audio fetch refused for %s via %s client", video_id, client)
                continue

            for path in Path(workdir).iterdir():
                if path.suffix.lower() in {".m4a", ".webm", ".opus", ".mp3", ".mp4", ".ogg"}:
                    return str(path)
            # Downloaded nothing but was not refused: nothing more to try.
            return None

        raise AudioForbidden(
            "every yt-dlp player client was refused for "
            f"{video_id} ({'; '.join(refusals)}). This IP is blocked on the audio "
            "endpoint too — set DEEPCLIP_YTDLP_PROXY / WEBSHARE_PROXY_USER+PASS "
            "(residential proxy) or YTDLP_COOKIES_FILE to route around it."
        )

    def _transcribe_file(self, audio_path: str, video_id: str) -> Transcript:
        model = self._load()
        segments, info = model.transcribe(audio_path, beam_size=5, vad_filter=True)
        cues = [
            TranscriptCue(t_start=float(s.start), t_end=float(s.end), text=s.text.strip())
            for s in segments
            if s.text and s.text.strip()
        ]
        return Transcript(
            video_id=video_id,
            kind="whisper",
            lang=getattr(info, "language", None),
            cues=cues,
        )


# One shared transcriber per process, so the Whisper model is loaded once rather
# than per video. Loading it per call (the previous behaviour) dominated a build's
# wall-clock. Guarded because a build is single-threaded through this path.
_SHARED_TRANSCRIBER: "WhisperTranscriber | None" = None


def _shared_transcriber() -> "WhisperTranscriber":
    global _SHARED_TRANSCRIBER
    if _SHARED_TRANSCRIBER is None:
        _SHARED_TRANSCRIBER = WhisperTranscriber()
    return _SHARED_TRANSCRIBER


def fetch_with_whisper_fallback(
    video_id: str,
    caption_fetcher,
    transcriber: WhisperTranscriber | None = None,
) -> Transcript | None:
    """The full stage-4 chain: manual → auto → whisper → None.

    Captions are always tried first, and they are free. Whisper only ever runs
    when they are genuinely absent — or when the caption endpoint is IP-blocked,
    which is exactly the case this path is meant to rescue (audio comes from a
    different host that is not blocked).
    """
    try:
        transcript = caption_fetcher.fetch(video_id)
    except Exception as exc:  # noqa: BLE001 - includes TranscriptIpBlocked
        # Captions unavailable (blocked or errored). Fall through to Whisper if
        # enabled; otherwise re-raise so the caller can report the block.
        if not whisper_enabled():
            raise
        log.info("captions unavailable for %s (%s); using Whisper", video_id, type(exc).__name__)
        transcript = None
    if transcript is not None:
        return transcript
    if not whisper_enabled():
        return None
    return (transcriber or _shared_transcriber()).transcribe(video_id)
