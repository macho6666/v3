from typing import Dict, List
from .models import Candidate
from .text_utils import normalize, strip_volume_prefix


def build_candidates(episodes: Dict[int, str]) -> List[Candidate]:
    result: List[Candidate] = []

    for number, original_title in sorted(episodes.items()):
        cleaned = strip_volume_prefix(original_title)

        variants = [("전체", cleaned)]
        if "/" in cleaned:
            parts = [normalize(part) for part in cleaned.split("/") if normalize(part)]
            variants.extend(("분리", part) for part in parts)

        seen = set()
        index = 1

        for kind, title in variants:
            title = normalize(title)
            if not title or title in seen:
                continue
            seen.add(title)

            result.append(
                Candidate(
                    candidate_id=f"{number}:{index}",
                    episode_number=number,
                    compare_title=title,
                    output_title=title,
                    kind=kind,
                )
            )
            index += 1

    return result
