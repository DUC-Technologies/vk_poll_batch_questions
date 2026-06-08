from typing import Optional
from vkbottle import Keyboard, KeyboardButtonColor, Callback
from models import Question

class SurveyPresenter:
    """Генератор UI-контента (текст и клавиатуры) для вопросов опроса."""

    @staticmethod
    def render_question(
        q: Question,
        block_name: str,
        chosen_idx: Optional[int],
        is_first: bool,
        is_last: bool,
        current_idx: int,
        total_screens: int,
        global_idx: int,
    ) -> tuple[str, str]:
        
        lines = []
        if is_first:
            lines.append(f"📋 Блок: {block_name} (Часть {current_idx + 1} из {total_screens})")
            lines.append("──────────────────────────")
        
        lines.append(f"{global_idx}. {q.question}")
        text = "\n".join(lines)
        
        keyboard = Keyboard(inline=True)
        
        for opt_idx, opt in enumerate(q.options):
            if opt_idx > 0:
                keyboard.row()
            color = KeyboardButtonColor.POSITIVE if chosen_idx == opt_idx else KeyboardButtonColor.SECONDARY
            keyboard.add(
                Callback(label=opt, payload={"act": "select", "q_id": q.id, "opt_idx": opt_idx}),
                color=color
            )
        
        if is_last:
            keyboard.row()
            if current_idx > 0:
                keyboard.add(Callback("⬅️ Назад", payload={"act": "prev"}), color=KeyboardButtonColor.PRIMARY)
            
            if current_idx == total_screens - 1:
                keyboard.add(Callback("📥 Завершить", payload={"act": "submit"}), color=KeyboardButtonColor.POSITIVE)
            else:
                keyboard.add(Callback("Далее ➡️", payload={"act": "next"}), color=KeyboardButtonColor.PRIMARY)
                
        return text, keyboard.get_json()
    