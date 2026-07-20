import asyncio
from pathlib import Path

import pytest

from scripts.prebuild import RunStats, load_queries, prebuild
from services.worker.pipeline.transcripts_whisper import (
    WhisperTranscriber,
    estimate_cost_usd,
    fetch_with_whisper_fallback,
    whisper_enabled,
)
from services.worker.sources.base import Transcript, TranscriptCue


@pytest.fixture
def whisper_on(monkeypatch):
    monkeypatch.setenv("DEEPCLIP_WHISPER", "1")


@pytest.fixture
def whisper_off(monkeypatch):
    monkeypatch.delenv("DEEPCLIP_WHISPER", raising=False)


# -- whisper flag -------------------------------------------------------


def test_whisper_disabled_by_default(whisper_off):
    """It costs money and needs a GPU; it must never run implicitly."""
    assert whisper_enabled() is False


def test_whisper_enabled_via_env(whisper_on):
    assert whisper_enabled() is True


def test_transcribe_returns_none_when_disabled(whisper_off):
    assert WhisperTranscriber().transcribe("abc") is None


def test_cost_estimate():
    assert estimate_cost_usd(600) == pytest.approx(0.06)
    assert estimate_cost_usd(0) == 0.0
    assert estimate_cost_usd(-100) == 0.0


# -- fallback chain -----------------------------------------------------


class FakeCaptions:
    def __init__(self, transcript=None):
        self._t = transcript
        self.calls = 0

    def fetch(self, video_id):
        self.calls += 1
        return self._t


class FakeTranscriber:
    def __init__(self):
        self.calls = 0

    def transcribe(self, video_id, **kw):
        self.calls += 1
        return Transcript(video_id, "whisper", "en", [TranscriptCue(0, 5, "text")])


def a_transcript():
    return Transcript("v1", "manual", "en", [TranscriptCue(0, 5, "hi")])


def test_captions_win_and_whisper_never_runs(whisper_on):
    """Captions are free. Whisper must only run when they are genuinely absent."""
    captions = FakeCaptions(a_transcript())
    whisper = FakeTranscriber()
    result = fetch_with_whisper_fallback("v1", captions, whisper)
    assert result.kind == "manual"
    assert whisper.calls == 0, "paid for whisper when captions existed"


def test_whisper_runs_when_captions_missing(whisper_on):
    whisper = FakeTranscriber()
    result = fetch_with_whisper_fallback("v1", FakeCaptions(None), whisper)
    assert result.kind == "whisper"
    assert whisper.calls == 1


def test_no_whisper_when_flag_off(whisper_off):
    whisper = FakeTranscriber()
    assert fetch_with_whisper_fallback("v1", FakeCaptions(None), whisper) is None
    assert whisper.calls == 0


def test_audio_workdir_is_removed(whisper_on, monkeypatch, tmp_path):
    """Leftover audio would turn a transient decode into hosting (B4)."""
    created: list[str] = []
    real_mkdtemp = __import__("tempfile").mkdtemp

    def tracking_mkdtemp(*a, **kw):
        d = real_mkdtemp(*a, **kw)
        created.append(d)
        return d

    monkeypatch.setattr("tempfile.mkdtemp", tracking_mkdtemp)
    monkeypatch.setattr(
        WhisperTranscriber, "_download_audio", staticmethod(lambda *a, **kw: None)
    )
    WhisperTranscriber().transcribe("abc")
    assert created, "expected a workdir"
    for d in created:
        assert not Path(d).exists(), f"audio workdir survived: {d}"


def test_workdir_removed_even_on_crash(whisper_on, monkeypatch):
    created: list[str] = []
    real_mkdtemp = __import__("tempfile").mkdtemp

    def tracking_mkdtemp(*a, **kw):
        d = real_mkdtemp(*a, **kw)
        created.append(d)
        return d

    def boom(*a, **kw):
        raise RuntimeError("download exploded")

    monkeypatch.setattr("tempfile.mkdtemp", tracking_mkdtemp)
    monkeypatch.setattr(WhisperTranscriber, "_download_audio", staticmethod(boom))
    assert WhisperTranscriber().transcribe("abc") is None
    for d in created:
        assert not Path(d).exists(), "audio survived a crash"


# -- prebuild query loading ---------------------------------------------


def test_load_queries_skips_blanks_and_comments(tmp_path):
    f = tmp_path / "q.txt"
    f.write_text("gandhi\n\n# a comment\nmlk\n   \n")
    assert load_queries(str(f)) == ["gandhi", "mlk"]


def test_load_queries_dedupes_on_normalised_form(tmp_path):
    """Two queries normalising the same would build one page twice."""
    f = tmp_path / "q.txt"
    f.write_text("Mahatma Gandhi\nmahatma   gandhi\nGandhi's Salt March\ngandhis salt march\n")
    assert load_queries(str(f)) == ["Mahatma Gandhi", "Gandhi's Salt March"]


def test_load_queries_empty(tmp_path):
    f = tmp_path / "q.txt"
    f.write_text("# only comments\n\n")
    assert load_queries(str(f)) == []


# -- prebuild run stats -------------------------------------------------


def test_run_stats_summary_shape():
    s = RunStats(built=3, skipped=1, failed=2, cost_usd=1.234, quota_spent=500)
    out = s.summary()
    assert "built=3" in out and "failed=2" in out and "$1.23" in out


class FakeRepo:
    def __init__(self, pages=None):
        self._pages = pages or {}
        self.saved = []

    async def get_page(self, slug):
        return self._pages.get(slug)

    async def save_page(self, slug, mode, outline, page, status, cost=None):
        self.saved.append((slug, status))

    async def close(self):
        pass


def run_prebuild(monkeypatch, queries, repo, **kw):
    monkeypatch.setattr("scripts.prebuild.Repo.connect", staticmethod(lambda: _wrap(repo)))
    defaults = dict(budget_usd=100.0, quota_limit=10_000, dry_run=False, force=False)
    defaults.update(kw)
    return asyncio.run(prebuild(queries, **defaults))


async def _wrap(repo):
    return repo


def test_prebuild_skips_cached_pages(monkeypatch):
    """Resumability: a restart must not pay twice for what is already built."""
    repo = FakeRepo({"gandhi": {"status": "ready"}})
    stats = run_prebuild(monkeypatch, ["gandhi"], repo, dry_run=True)
    assert stats.skipped == 1
    assert stats.built == 0


def test_prebuild_dry_run_builds_nothing(monkeypatch):
    stats = run_prebuild(monkeypatch, ["a", "b"], FakeRepo(), dry_run=True)
    assert stats.built == 0
    assert stats.skipped == 2


def test_prebuild_force_ignores_cache(monkeypatch):
    """--force must not skip; with dry-run it should still count as considered."""
    repo = FakeRepo({"gandhi": {"status": "ready"}})
    stats = run_prebuild(monkeypatch, ["gandhi"], repo, dry_run=True, force=True)
    assert stats.skipped == 1  # dry-run counts it, but cache was not consulted


def test_prebuild_stops_on_budget(monkeypatch):
    """Budget is a hard ceiling — overrunning it costs real money."""
    repo = FakeRepo()
    stats = run_prebuild(monkeypatch, ["a"], repo, budget_usd=0.0, dry_run=True)
    assert stats.built == 0


def test_prebuild_stops_when_quota_nearly_gone(monkeypatch):
    repo = FakeRepo()
    stats = run_prebuild(monkeypatch, ["a", "b"], repo, quota_limit=100, dry_run=True)
    # Safety margin is 500u, so a 100u limit stops immediately.
    assert stats.built == 0
