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

DEFAULT_MODEL = "large-v3"
MAX_DURATION_S = 3600  # a 3-hour stream is not worth transcribing at $0.006/min


def whisper_enabled() -> bool:
    return os.environ.get("DEEPCLIP_WHISPER", "").lower() in {"1", "true", "yes"}


class WhisperUnavailable(RuntimeError):
    pass


def estimate_cost_usd(duration_s: int, rate_per_min: float = 0.006) -> float:
    return max(duration_s, 0) / 60.0 * rate_per_min


class WhisperTranscriber:
    """faster-whisper over ephemeral audio.

    The model is loaded lazily and reused: loading large-v3 costs seconds and
    gigabytes, so constructing one per video would dominate the run.
    """

    def __init__(self, model_size: str = DEFAULT_MODEL, device: str = "auto"):
        self.model_size = model_size
        self.device = device
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
        compute = "float16" if self.device in {"cuda", "auto"} else "int8"
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
        except WhisperUnavailable:
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
        """Audio-only fetch via yt-dlp. Never video, never retained."""
        try:
            import yt_dlp
        except ImportError as exc:  # pragma: no cover
            raise WhisperUnavailable("yt-dlp is not installed") from exc

        out = os.path.join(workdir, "%(id)s.%(ext)s")
        opts = {
            "format": "bestaudio/best",
            "outtmpl": out,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "64"}
            ],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False
            )
            duration = int(info.get("duration") or 0)
            if duration > max_duration_s:
                log.info(
                    "skipping whisper for %s: %ds exceeds %ds cap (~$%.2f)",
                    video_id, duration, max_duration_s, estimate_cost_usd(duration),
                )
                return None
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

        for path in Path(workdir).iterdir():
            if path.suffix in {".mp3", ".m4a", ".webm", ".opus"}:
                return str(path)
        return None

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


def fetch_with_whisper_fallback(
    video_id: str,
    caption_fetcher,
    transcriber: WhisperTranscriber | None = None,
) -> Transcript | None:
    """The full stage-4 chain: manual → auto → whisper → None.

    Captions are always tried first, and they are free. Whisper only ever runs
    when they are genuinely absent.
    """
    transcript = caption_fetcher.fetch(video_id)
    if transcript is not None:
        return transcript
    if not whisper_enabled():
        return None
    return (transcriber or WhisperTranscriber()).transcribe(video_id)
