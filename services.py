import asyncio
from typing import List, Dict, Any
from vkbottle import VKAPIError
from models import SurveyScreen, Question, UserSession
from presenter import SurveyPresenter

def parse_survey_data(raw_data: List[Dict[str, Any]]) -> List[SurveyScreen]:
    """Преобразует сырые данные в список объектов SurveyScreen."""
    screens = []
    for group in raw_data:
        block_name = group.get("block_name", "Без названия")
        questions = [Question(**q) for q in group.get("block", [])]
        screens.append(SurveyScreen(block_name=block_name, questions=questions))
    return screens


async def send_current_survey_block(api: Any, peer_id: int, session: UserSession) -> None:
    """Отправляет все сообщения текущего блока с обработкой Flood Control."""
    screen = session.current_screen
    start_global_idx = sum(len(s.questions) for s in session.screens[:session.current_screen_idx]) + 1
    
    for idx, q in enumerate(screen.questions):
        is_first = (idx == 0)
        is_last = (idx == len(screen.questions) - 1)
        chosen_idx = session.results.get(q.id)
        
        text, kb = SurveyPresenter.render_question(
            q=q,
            block_name=screen.block_name,
            chosen_idx=chosen_idx,
            is_first=is_first,
            is_last=is_last,
            current_idx=session.current_screen_idx,
            total_screens=session.total_screens,
            global_idx=start_global_idx + idx
        )
        
        retry_delays = [1, 3, 5, 10]
        msg = None
        
        for attempt, delay in enumerate(retry_delays + [0]):
            try:
                msg = await api.messages.send(peer_id=peer_id, message=text, keyboard=kb, random_id=0)
                break
            except VKAPIError as e:
                if e.code == 9 and attempt < len(retry_delays):
                    await asyncio.sleep(retry_delays[attempt])
                else:
                    raise e
        
        if msg:
            if isinstance(msg, int):
                msg_id = msg
            elif isinstance(msg, list) and msg:
                msg_id = msg[0] if isinstance(msg[0], int) else getattr(msg[0], "message_id", None)
            else:
                msg_id = getattr(msg, "message_id", None)
                
            if msg_id:
                session.active_message_ids.append(int(msg_id))
                session.q_to_msg_map[q.id] = int(msg_id)
        
        if not is_last:
            await asyncio.sleep(0.35)


async def delete_current_block_messages(api: Any, session: UserSession) -> None:
    """Удаляет отправленные сообщения текущего блока сессии."""
    if session.active_message_ids:
        try:
            ids_to_delete = [int(m_id) for m_id in session.active_message_ids]
            await api.messages.delete(message_ids=ids_to_delete, delete_for_all=1)
        except Exception:
            pass
        session.clear_message_tracking()
