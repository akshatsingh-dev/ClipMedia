"""Guard against the frontend and backend disagreeing about platform detection.

`ImportBox.tsx` decides whether to show the caption field; `reel_import.py`
decides whether the import is legal without one. If those two drift, a user
pastes a TikTok link, the UI never asks for a caption, and the backend rejects
it — a confusing failure with no obvious cause.

These tests parse the regexes out of the TSX and check both sides classify the
same URLs identically.
"""

import re
from pathlib import Path

import pytest

from services.worker.pipeline.reel_import import UnsupportedSource, resolve_platform

TSX = Path(__file__).resolve().parent.parent / "apps" / "web" / "components" / "ImportBox.tsx"

CASES = [
    ("https://www.youtube.com/watch?v=aircAruvnKk", "youtube"),
    ("https://youtu.be/aircAruvnKk", "youtube"),
    ("https://www.youtube.com/shorts/aircAruvnKk", "youtube"),
    ("https://www.youtube.com/embed/aircAruvnKk", "youtube"),
    ("https://www.instagram.com/reel/Cx1_ab-2/", "instagram"),
    ("https://instagram.com/p/ABC123", "instagram"),
    ("https://www.tiktok.com/@user/video/12345", "tiktok"),
    ("https://example.com/video/1", "unknown"),
    ("not a url at all", "unknown"),
]


def _js_regex_to_python(pattern: str) -> str:
    """JS and Python regex syntax overlap enough for these patterns.

    Only difference that matters here is the non-capturing-group and character
    class syntax, which is identical. \\d and \\w behave the same.
    """
    return pattern


@pytest.fixture(scope="module")
def tsx_patterns() -> dict[str, re.Pattern]:
    source = TSX.read_text()
    out = {}
    for name, key in (("YT", "youtube"), ("IG", "instagram"), ("TT", "tiktok")):
        m = re.search(rf"^const {name} = /(.+)/;$", source, re.MULTILINE)
        assert m, f"could not find the {name} regex in ImportBox.tsx"
        out[key] = re.compile(_js_regex_to_python(m.group(1)))
    return out


def frontend_detect(url: str, patterns: dict[str, re.Pattern]) -> str:
    for key in ("youtube", "instagram", "tiktok"):
        if patterns[key].search(url):
            return key
    return "unknown"


def backend_detect(url: str) -> str:
    try:
        return resolve_platform(url)[0]
    except UnsupportedSource:
        return "unknown"


@pytest.mark.parametrize("url,expected", CASES)
def test_frontend_matches_expected(url, expected, tsx_patterns):
    assert frontend_detect(url, tsx_patterns) == expected


@pytest.mark.parametrize("url,expected", CASES)
def test_backend_matches_expected(url, expected):
    assert backend_detect(url) == expected


@pytest.mark.parametrize("url,_", CASES)
def test_frontend_and_backend_agree(url, _, tsx_patterns):
    """The parity check itself. Drift here produces a confusing dead end."""
    assert frontend_detect(url, tsx_patterns) == backend_detect(url), (
        f"frontend and backend disagree about {url!r}"
    )


def test_caption_requirement_is_consistent(tsx_patterns):
    """Platforms the UI asks a caption for must be exactly those the backend
    refuses without one."""
    ui_needs_caption = set()
    source = TSX.read_text()
    m = re.search(r"const NEEDS_CAPTION: Platform\[\] = \[(.*?)\];", source, re.DOTALL)
    assert m, "could not find NEEDS_CAPTION in ImportBox.tsx"
    ui_needs_caption = set(re.findall(r'"(\w+)"', m.group(1)))

    backend_needs_caption = set()
    for platform, url in (
        ("instagram", "https://www.instagram.com/reel/ABC/"),
        ("tiktok", "https://www.tiktok.com/@u/video/1"),
        ("youtube", "https://youtu.be/aircAruvnKk"),
    ):
        from services.worker.pipeline.build import BuildDeps
        from services.worker.pipeline.reel_import import import_seed

        try:
            import_seed(url, BuildDeps(youtube=None, llm=None, embedder=None))
        except UnsupportedSource as exc:
            if "caption text" in str(exc):
                backend_needs_caption.add(platform)
        except Exception:
            # YouTube gets further and fails on the null deps; that is fine —
            # it means it did not demand a caption.
            pass

    assert ui_needs_caption == backend_needs_caption, (
        f"UI asks for captions on {ui_needs_caption} but backend requires them "
        f"on {backend_needs_caption}"
    )
