from dataclasses import dataclass, field
from typing import List, Dict

@dataclass(frozen=True)
class Question:
    id: str
    question: str
    options: List[str]


@dataclass(frozen=True)
class SurveyScreen:
    block_name: str
    questions: List[Question]


@dataclass
class UserSession:
    screens: List[SurveyScreen]
    current_screen_idx: int = 0
    results: Dict[str, int] = field(default_factory=dict)
    active_message_ids: List[int] = field(default_factory=list)
    q_to_msg_map: Dict[str, int] = field(default_factory=dict)

    @property
    def current_screen(self) -> SurveyScreen:
        return self.screens[self.current_screen_idx]

    @property
    def total_screens(self) -> int:
        return len(self.screens)

    def is_current_screen_complete(self) -> bool:
        return all(q.id in self.results for q in self.current_screen.questions)

    def move_next(self) -> bool:
        if self.current_screen_idx < self.total_screens - 1:
            self.current_screen_idx += 1
            return True
        return False

    def move_prev(self) -> bool:
        if self.current_screen_idx > 0:
            self.current_screen_idx -= 1
            return True
        return False

    def clear_message_tracking(self) -> None:
        self.active_message_ids.clear()
        self.q_to_msg_map.clear()


USER_SESSIONS: Dict[int, UserSession] = {}
