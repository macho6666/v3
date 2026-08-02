import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import parse_qsl, urlsplit


def cache_dir() -> Path:
    path = Path.home() / "AppData" / "Local" / "EpubHeadingTool"
    path.mkdir(parents=True, exist_ok=True)
    return path


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    product_no = query.get("productNo", "")
    if product_no:
        return f"https://series.naver.com/novel/detail.series?productNo={product_no}"
    return url.strip()


def cache_path(url: str) -> Path:
    digest = hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()[:16]
    return cache_dir() / f"{digest}.json"


def save_cache(url: str, episodes: Dict[int, str], expected_total: Optional[int]) -> Path:
    payload = {
        "url": canonical_url(url),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "expected_total": expected_total,
        "episodes": {str(k): v for k, v in sorted(episodes.items())},
    }
    path = cache_path(url)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_cache(url: str):
    path = cache_path(url)
    if not path.exists():
        return None

    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": path,
        "saved_at": data.get("saved_at", ""),
        "expected_total": data.get("expected_total"),
        "episodes": {int(k): v for k, v in data.get("episodes", {}).items()},
    }


def delete_cache(url: str) -> bool:
    path = cache_path(url)
    if path.exists():
        path.unlink()
        return True
    return False
