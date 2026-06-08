import json
import redis.asyncio as aioredis
from vkbottle import Keyboard, KeyboardButtonColor, Text, VKAPIError
from vkbottle.bot import Bot, Message, MessageEvent

from config import BOT_TOKEN, INPUT_SURVEY_DATA, SCORE_MAP
from models import USER_SESSIONS, UserSession
from presenter import SurveyPresenter
from services import parse_survey_data, send_current_survey_block, delete_current_block_messages
from infra import idempotent_filter, redis_debounce_queue


redis_client = aioredis.from_url("redis://localhost:6379")
bot = Bot(token=BOT_TOKEN)


@redis_debounce_queue(redis_client, name="edit_keyboard", delay=1.3, max_wait=3.0)
async def queue_edit_message(user_id: int, message_id: int, click_data: dict):
    """Вызывается воркером автоматически, когда истечет таймер debounce."""
    if user_id not in USER_SESSIONS:
        return
        
    session = USER_SESSIONS[user_id]
    q_id = click_data["q_id"]
    opt_idx = click_data["opt_idx"]
    
    screen = session.current_screen
    q_idx = next((i for i, q in enumerate(screen.questions) if q.id == q_id), None)
    if q_idx is None:
        return
        
    start_global_idx = sum(len(s.questions) for s in session.screens[:session.current_screen_idx]) + 1
    
    text, kb = SurveyPresenter.render_question(
        q=screen.questions[q_idx],
        block_name=screen.block_name,
        chosen_idx=opt_idx,
        is_first=(q_idx == 0),
        is_last=(q_idx == len(screen.questions) - 1),
        current_idx=session.current_screen_idx,
        total_screens=session.total_screens,
        global_idx=start_global_idx + q_idx
    )
    
    await bot.api.messages.edit(
        peer_id=user_id, message_id=message_id, message=text, keyboard=kb
    )

@bot.on.message(text=["привет", "начать", "старт", "меню", "здравствуйте", "Начать тест", "Старт", "Начать"])
async def send_welcome(message: Message):
    start_keyboard = Keyboard(one_time=False, inline=False)
    start_keyboard.add(Text("🚀 Начать тест"), color=KeyboardButtonColor.PRIMARY)
    await message.answer(
        "👋 Здравствуйте! Нажмите кнопку ниже, чтобы запустить оценку управленческих навыков.",
        keyboard=start_keyboard
    )

@bot.on.message(text=["🚀 Начать тест", "/опрос"])
async def start_survey(message: Message):
    peer_id = message.peer_id
    if peer_id in USER_SESSIONS:
        await delete_current_block_messages(bot.api, USER_SESSIONS[peer_id])
        
    screens = parse_survey_data(INPUT_SURVEY_DATA)
    session = UserSession(screens=screens)
    USER_SESSIONS[peer_id] = session
    
    intro_text = (
        "Перед вами список из 40 управленческих навыков. Пожалуйста, оцените свой собственный "
        "уровень владения каждым из этих навыков по шкале:\n"
        "- Плохо\n"
        "- Скорее плохо\n"
        "- Скорее хорошо\n"
        "- Отлично"
    )
    
    intro_msg = await bot.api.messages.send(
        peer_id=peer_id, 
        message=intro_text, 
        keyboard=Keyboard(), 
        random_id=0,
    )
    intro_id = intro_msg if isinstance(intro_msg, int) else getattr(intro_msg, "message_id", None)
    if intro_id:
        session.active_message_ids.append(int(intro_id))

    await send_current_survey_block(bot.api, peer_id, session)


@bot.on.raw_event(event="message_event", dataclass=MessageEvent)
@idempotent_filter(redis_client, ttl=1.0)
async def callback_controller(event: MessageEvent):
    peer_id = event.peer_id
    payload = event.payload
    action = payload.get("act")
    
    if peer_id not in USER_SESSIONS:
        try:
            await event.ctx_api.messages.send_message_event_answer(
                event_id=event.event_id, user_id=event.user_id, peer_id=event.peer_id,
                event_data=json.dumps({"type": "show_snackbar", "text": "⚠️ Сессия истекла. Нажмите 'Начать тест'."})
            )
        except Exception:
            pass
        return

    session = USER_SESSIONS[peer_id]

    match action:
        case "select":
            q_id, opt_idx = payload["q_id"], payload["opt_idx"]
            screen = session.current_screen
            q_idx = next((i for i, q in enumerate(screen.questions) if q.id == q_id), None)
            
            if q_idx is None:
                try:
                    await event.ctx_api.messages.send_message_event_answer(
                        event_id=event.event_id, user_id=event.user_id, peer_id=event.peer_id,
                        event_data=json.dumps({
                            "type": "show_snackbar", "text": "⚠️ Сессия обновлена. Используйте актуальные кнопки!"
                        })
                    )
                except Exception:
                    pass
                return
                
            # обновляем состояние сессии для корректных проверок "Next"
            session.results[q_id] = opt_idx
            
            msg_id = session.q_to_msg_map.get(q_id)
            if msg_id:
                # пушим задачу в очередь
                await queue_edit_message(peer_id, msg_id, {"q_id": q_id, "opt_idx": opt_idx})
                
        case "next":
            if not session.is_current_screen_complete():
                await event.ctx_api.messages.send_message_event_answer(
                    event_id=event.event_id, user_id=event.user_id, peer_id=event.peer_id,
                    event_data=json.dumps({"type": "show_snackbar", "text": "⚠️ Оцените все навыки в текущем блоке!"})
                )
                return
            
            await delete_current_block_messages(event.ctx_api, session)
            if session.move_next():
                await send_current_survey_block(event.ctx_api, peer_id, session)
                
        case "prev":
            await delete_current_block_messages(event.ctx_api, session)
            if session.move_prev():
                await send_current_survey_block(event.ctx_api, peer_id, session)
                
        case "submit":
            if not session.is_current_screen_complete():
                await event.ctx_api.messages.send_message_event_answer(
                    event_id=event.event_id, user_id=event.user_id, peer_id=event.peer_id,
                    event_data=json.dumps({"type": "show_snackbar", "text": "⚠️ Пожалуйста, завершите оценку текущего блока."})
                )
                return

            await delete_current_block_messages(event.ctx_api, session)
            
            result_lines = ["🎉 Тестирование успешно пройдено! Ваши ответы:\n"]
            final_results = {}
            
            for scr in session.screens:
                for q in scr.questions:
                    chosen_idx = session.results.get(q.id)
                    ans_text = q.options[chosen_idx] if chosen_idx is not None else "Нет ответа"
                    result_lines.append(f"❓ {q.question}\n👉 Оценка: {ans_text}\n")
                    final_results[q.id] = {
                        "question_text": q.question, "user_answer": ans_text, "score": SCORE_MAP.get(ans_text, 0)
                    }

            await event.ctx_api.messages.send(
                peer_id=peer_id, message="\n".join(result_lines), keyboard=Keyboard(), random_id=0
            )
            print(json.dumps(final_results, ensure_ascii=False, indent=4))
            del USER_SESSIONS[peer_id]
        
    # убираем анимацию колесика на кнопке для UX
    try:
        await event.ctx_api.messages.send_message_event_answer(
            event_id=event.event_id, user_id=event.user_id, peer_id=event.peer_id
        )
    except Exception:
        pass

@bot.error_handler.register_error_handler(VKAPIError)
async def handle_vk_flood_error(e: VKAPIError):
    if e.code == 9:
        print("⚠️ [Системный перехват] VK API Error 9: Зафиксирован Flood Control.")
    else:
        raise e
    