from dataclasses import dataclass, field
import json
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
        
    def to_json(self) -> str:
        """Превращает сессию в JSON-строку для хранения в Redis."""
        # Сами экраны (screens) статичны и берутся из конфига, 
        # но для автономности структуры сохраняем всё дерево.
        data = {
            "current_screen_idx": self.current_screen_idx,
            "results": self.results,
            "active_message_ids": self.active_message_ids,
            "q_to_msg_map": self.q_to_msg_map,
            "screens": [
                {
                    "block_name": s.block_name,
                    "questions": [{"id": q.id, "question": q.question, "options": q.options} for q in s.questions]
                }
                for s in self.screens
            ]
        }
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "UserSession":
        """Восстанавливает объект UserSession из JSON-строки, полученной из Redis."""
        data = json.loads(json_str)
        
        screens = [
            SurveyScreen(
                block_name=s["block_name"],
                questions=[Question(**q) for q in s["questions"]]
            )
            for s in data["screens"]
        ]
        
        return cls(
            screens=screens,
            current_screen_idx=data["current_screen_idx"],
            results=data["results"],
            active_message_ids=data["active_message_ids"],
            q_to_msg_map={k: int(v) for k, v in data["q_to_msg_map"].items()}
        )
