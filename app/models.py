from dataclasses import dataclass, field
from typing import List


@dataclass
class MatchLocation:
    file_path: str
    paragraph_index: int
    previous_text: str = ""
    current_text: str = ""
    next_text: str = ""
    consecutive_group_size: int = 1
    global_order: int = 0
    body_hash: str = ""
    body_preview: str = ""
    body_end_index: int = -1


@dataclass
class Candidate:
    candidate_id: str
    episode_number: int
    compare_title: str
    output_title: str
    kind: str
    found_count: int = 0
    matches: List[MatchLocation] = field(default_factory=list)
    status: str = ""
    include: bool = False
    selected_match_index: int = 0
    same_title_episode_count: int = 1
    duplicate_action: str = "none"
    duplicate_reason: str = ""
