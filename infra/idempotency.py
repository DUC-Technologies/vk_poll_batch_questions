import json
import logging
from functools import wraps
from vkbottle.bot import MessageEvent


logger = logging.getLogger("infra.idempotency")

def idempotent_filter(redis_client, ttl=1):
    """Отсекает дубликаты кликов по одной и той же кнопке в течение TTL."""
    def decorator(func):
        @wraps(func)
        async def wrapper(event: MessageEvent, *args, **kwargs):
            user_id = event.user_id
            message_id = event.conversation_message_id 
            
            payload_str = json.dumps(event.payload, sort_keys=True)
            
            lock_key = f"lock:{user_id}:{message_id}:{payload_str}"
            
            is_unique = await redis_client.set(lock_key, "1", px=int(ttl * 1000), nx=True)
            
            if not is_unique:
                # клик повторный — убираем спиннер загрузки в вк
                logger.info(
                    f"🛑 [Idempotency] Отсечен дубликат клика! "
                    f"Юзер: {user_id} | Msg ID: {message_id} | Payload: {event.payload}"
                )
                try:
                    await event.ctx_api.messages.send_message_event_answer(
                        event_id=event.event_id, user_id=event.user_id, peer_id=event.peer_id
                    )
                except Exception:
                    pass
                return
                
            return await func(event, *args, **kwargs)
        return wrapper
    return decorator