import html
import re

SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")
VOLUME_PREFIX_RE = re.compile(r"^\s*\d+\s*권\s*[-–—:：]\s*")


def normalize(text: str) -> str:
    return SPACE_RE.sub(" ", html.unescape(text or "").replace("\xa0", " ")).strip()


def visible_text(fragment: str) -> str:
    return normalize(TAG_RE.sub("", html.unescape(fragment or "")))


def compare_key(text: str) -> str:
    # 비교할 때는 모든 공백 제거
    return re.sub(r"\s+", "", normalize(text))


def strip_volume_prefix(title: str) -> str:
    return VOLUME_PREFIX_RE.sub("", normalize(title))
