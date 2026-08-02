import hashlib
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

from .models import Candidate, MatchLocation
from .text_utils import compare_key, normalize, visible_text

P_RE = re.compile(r"<p(?P<attrs>\s[^>]*)?>(?P<inner>.*?)</p>", re.I | re.S)


def _html_files(temp: Path):
    return sorted(
        list(temp.rglob("*.xhtml"))
        + list(temp.rglob("*.html"))
        + list(temp.rglob("*.htm")),
        key=lambda path: path.as_posix(),
    )


def _body_hash(paragraphs: List[str]) -> str:
    normalized = "\n".join(
        compare_key(paragraph)
        for paragraph in paragraphs
        if compare_key(paragraph)
    )
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def analyze_epub(epub_path: Path, candidates: Iterable[Candidate]) -> Dict[str, Candidate]:
    candidate_list = list(candidates)

    candidates_by_key: Dict[str, List[Candidate]] = {}
    for candidate in candidate_list:
        candidates_by_key.setdefault(
            compare_key(candidate.compare_title),
            [],
        ).append(candidate)

    for same_key_candidates in candidates_by_key.values():
        same_key_candidates.sort(
            key=lambda candidate: (
                candidate.episode_number,
                candidate.candidate_id,
            )
        )

    all_title_keys: Set[str] = set(candidates_by_key)
    raw_locations_by_key: Dict[str, List[MatchLocation]] = {
        key: [] for key in candidates_by_key
    }

    global_order = 0

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)

        with zipfile.ZipFile(epub_path, "r") as archive:
            archive.extractall(temp)

        for file_path in _html_files(temp):
            raw = file_path.read_text(encoding="utf-8", errors="replace")
            matches = list(P_RE.finditer(raw))
            texts = [visible_text(match.group("inner")) for match in matches]
            keys = [compare_key(text) for text in texts]

            index = 0
            while index < len(matches):
                key = keys[index]

                if key not in candidates_by_key:
                    global_order += 1
                    index += 1
                    continue

                group_start = index
                group_end = index

                while (
                    group_end + 1 < len(matches)
                    and keys[group_end + 1] == key
                ):
                    group_end += 1

                body_start = group_end + 1
                body_end = len(matches)

                for next_index in range(body_start, len(matches)):
                    if keys[next_index] in all_title_keys:
                        body_end = next_index
                        break

                body_paragraphs = texts[body_start:body_end]
                preview = " ".join(
                    paragraph for paragraph in body_paragraphs[:3]
                    if paragraph
                )[:240]

                raw_locations_by_key[key].append(
                    MatchLocation(
                        file_path=file_path.relative_to(temp).as_posix(),
                        paragraph_index=group_start,
                        previous_text=texts[group_start - 1] if group_start > 0 else "",
                        current_text=texts[group_start],
                        next_text=texts[group_end + 1] if group_end + 1 < len(texts) else "",
                        consecutive_group_size=group_end - group_start + 1,
                        global_order=global_order,
                        body_hash=_body_hash(body_paragraphs),
                        body_preview=preview,
                        body_end_index=body_end,
                    )
                )

                global_order += group_end - group_start + 1
                index = group_end + 1

    result: Dict[str, Candidate] = {}

    for key, same_key_candidates in candidates_by_key.items():
        locations = sorted(
            raw_locations_by_key.get(key, []),
            key=lambda location: location.global_order,
        )

        candidate_count = len(same_key_candidates)
        location_count = len(locations)

        # 같은 제목이 서로 다른 회차에 실제 사용된 경우:
        # 등장 순서대로 회차에 배정하고 자동 삭제하지 않는다.
        if candidate_count >= 2:
            for index, candidate in enumerate(same_key_candidates):
                candidate.same_title_episode_count = candidate_count

                if index < location_count:
                    candidate.matches = [locations[index]]
                    candidate.found_count = 1
                    candidate.include = True
                    candidate.status = f"동일제목 다른회차 {candidate_count}개"
                    candidate.duplicate_action = "keep"
                    candidate.duplicate_reason = "서로 다른 회차의 동일 제목"
                else:
                    candidate.matches = []
                    candidate.found_count = 0
                    candidate.include = False
                    candidate.status = "동일제목 회차 위치 부족"
                    candidate.duplicate_action = "none"
                    candidate.duplicate_reason = "EPUB 내 위치 부족"

                result[candidate.candidate_id] = candidate

            continue

        candidate = same_key_candidates[0]
        candidate.same_title_episode_count = 1
        candidate.matches = locations
        candidate.found_count = len(locations)

        if not locations:
            candidate.status = "미발견"
            candidate.include = False
            candidate.duplicate_action = "none"
            candidate.duplicate_reason = "EPUB에서 제목을 찾지 못함"

        elif len(locations) == 1:
            location = locations[0]
            candidate.include = True

            if location.consecutive_group_size >= 2:
                candidate.status = (
                    f"연속중복 {location.consecutive_group_size}개 · 제목 정리"
                )
                candidate.duplicate_action = "delete_consecutive_titles"
                candidate.duplicate_reason = "같은 제목이 연속으로 반복됨"
            else:
                candidate.status = "정상"
                candidate.duplicate_action = "keep"
                candidate.duplicate_reason = "중복 없음"

        else:
            hashes = [location.body_hash for location in locations]
            non_empty_hashes = [value for value in hashes if value]

            same_body = (
                len(non_empty_hashes) >= 2
                and len(set(non_empty_hashes)) == 1
            )

            candidate.include = True

            if same_body:
                candidate.status = (
                    f"동일본문중복 {len(locations)}곳 · 뒤쪽 삭제"
                )
                candidate.duplicate_action = "delete_duplicate_sections"
                candidate.duplicate_reason = "제목과 본문 해시가 동일함"
            else:
                candidate.status = (
                    f"같은제목 다른본문 {len(locations)}곳 · 유지"
                )
                candidate.duplicate_action = "keep_all"
                candidate.duplicate_reason = "본문 해시가 서로 다름"

        result[candidate.candidate_id] = candidate

    return result


def convert_epub(
    source: Path,
    destination: Path,
    selected: Iterable[Candidate],
    all_candidates: Iterable[Candidate],
    heading: str = "h2",
):
    selected_list = list(selected)
    all_candidate_list = list(all_candidates)

    all_title_keys: Set[str] = {
        compare_key(candidate.compare_title)
        for candidate in all_candidate_list
    }

    changed_ids: List[str] = []
    deleted_paragraphs = 0
    changed_files = 0
    collisions: List[str] = []
    warnings: List[str] = []

    transform_targets: Dict[Tuple[str, int], Candidate] = {}
    delete_ranges: Dict[str, List[Tuple[int, int]]] = {}

    for candidate in selected_list:
        if not candidate.matches:
            continue

        # 서로 다른 회차의 동일 제목은 각자 배정된 위치만 변환
        if candidate.same_title_episode_count >= 2:
            location = candidate.matches[0]
            transform_targets[
                (location.file_path, location.paragraph_index)
            ] = candidate
            continue

        first_location = candidate.matches[0]
        target_key = (
            first_location.file_path,
            first_location.paragraph_index,
        )

        if target_key in transform_targets:
            collisions.append(
                f"{candidate.episode_number}화 {candidate.output_title}"
            )
            continue

        transform_targets[target_key] = candidate

        if candidate.duplicate_action == "delete_consecutive_titles":
            if first_location.consecutive_group_size > 1:
                start = first_location.paragraph_index + 1
                end = (
                    first_location.paragraph_index
                    + first_location.consecutive_group_size
                )
                delete_ranges.setdefault(
                    first_location.file_path,
                    [],
                ).append((start, end))

        elif candidate.duplicate_action == "delete_duplicate_sections":
            for duplicate_location in candidate.matches[1:]:
                delete_ranges.setdefault(
                    duplicate_location.file_path,
                    [],
                ).append(
                    (
                        duplicate_location.paragraph_index,
                        duplicate_location.body_end_index,
                    )
                )

        elif candidate.duplicate_action == "keep_all":
            # 같은 제목이지만 다른 본문이면 첫 위치만 회차 제목으로 변환하고,
            # 나머지는 안전을 위해 그대로 둔다.
            warnings.append(
                f"{candidate.episode_number}화 {candidate.output_title} | "
                f"같은 제목 다른 본문 {len(candidate.matches)}곳 자동 삭제 안 함"
            )

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)

        with zipfile.ZipFile(source, "r") as archive:
            archive.extractall(temp)

        for file_path in _html_files(temp):
            relative_path = file_path.relative_to(temp).as_posix()
            raw = file_path.read_text(encoding="utf-8", errors="replace")
            matches = list(P_RE.finditer(raw))

            delete_indexes: Set[int] = set()
            for start, end in delete_ranges.get(relative_path, []):
                for index in range(
                    max(0, start),
                    min(end, len(matches)),
                ):
                    delete_indexes.add(index)

            parts = []
            last = 0
            touched = False

            for index, match in enumerate(matches):
                parts.append(raw[last:match.start()])

                if index in delete_indexes:
                    deleted_paragraphs += 1
                    touched = True
                else:
                    candidate = transform_targets.get(
                        (relative_path, index)
                    )

                    if candidate is None:
                        parts.append(match.group(0))
                    else:
                        attrs = match.group("attrs") or ""
                        parts.append(
                            f"<{heading}{attrs}>"
                            f"{candidate.episode_number}화 "
                            f"{candidate.output_title}"
                            f"</{heading}>"
                        )
                        changed_ids.append(candidate.candidate_id)
                        touched = True

                last = match.end()

            parts.append(raw[last:])

            if touched:
                file_path.write_text(
                    "".join(parts),
                    encoding="utf-8",
                )
                changed_files += 1

        mimetype = temp / "mimetype"

        with zipfile.ZipFile(destination, "w") as archive:
            if mimetype.exists():
                archive.write(
                    mimetype,
                    "mimetype",
                    compress_type=zipfile.ZIP_STORED,
                )

            for file_path in temp.rglob("*"):
                if file_path.is_file() and file_path != mimetype:
                    archive.write(
                        file_path,
                        file_path.relative_to(temp).as_posix(),
                        compress_type=zipfile.ZIP_DEFLATED,
                    )

    missing = [
        f"{candidate.episode_number}화 {candidate.output_title}"
        for candidate in selected_list
        if candidate.candidate_id not in changed_ids
    ]

    return {
        "changed_files": changed_files,
        "changed_titles": len(changed_ids),
        "deleted_paragraphs": deleted_paragraphs,
        "missing": missing,
        "collisions": collisions,
        "warnings": warnings,
    }
