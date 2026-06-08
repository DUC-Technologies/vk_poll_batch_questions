import json
import time
import logging
from functools import wraps

logger = logging.getLogger("infra.queue")
TASK_REGISTRY = {}

def redis_debounce_queue(redis_client, name, delay=0.3, max_wait=2.0):
    """
    Декоратор для группировки и откладывания вызовов.
    Схлапываем несколько вызовов, если они обращены к одному message. 
    Откладываем каждый раз, если видим, что состояние обновилось, но не больше макс задержки. 
    """
    def decorator(func):
        TASK_REGISTRY[name] = func
        
        @wraps(func)
        async def wrapper(user_id: int, message_id: int, click_data: dict, *args, **kwargs):
            hash_key = f"edit_state:{user_id}:{message_id}"
            zset_key = f"queue:{name}"
            task_id = f"{user_id}:{message_id}"
            now = time.time()
            
            state = await redis_client.hgetall(hash_key)
            status = state.get(b'status', b'').decode() if isinstance(state.get(b'status'), bytes) else state.get('status', '')
            
            # Если воркер ПРЯМО СЕЙЧАС отправляет запрос в ВК
            if status == 'processing':
                # Не ломаем текущую отправку, а готовим данные для СЛЕДУЮЩЕГО кадра
                await redis_client.hdel(hash_key, 'status')
                first_click_at = now
                await redis_client.hset(hash_key, 'first_click_at', str(now))
                logger.info(f"🔄 [Queue] Воркер занят отправкой {task_id}. Записываем новый клик в буфер для следующего такта.")
            else:
                fc_val = state.get(b'first_click_at') or state.get('first_click_at')
                first_click_at = float(fc_val) if fc_val else now
                if not fc_val:
                    await redis_client.hset(hash_key, 'first_click_at', str(now))
            
            # схлапываем клики
            await redis_client.hset(hash_key, 'payload', json.dumps(click_data))
            
            time_passed = now - first_click_at
            
            if time_passed < max_wait:
                score = now + delay
                await redis_client.zadd(zset_key, {task_id: score})
                
                if time_passed == 0:
                    logger.info(f"📥 [Queue] Первый клик серии ({task_id}). Таймер запущен на +{delay}с")
                else:
                    logger.info(
                        f"⚡ [Queue] СХЛАПЫВАНИЕ! Юзер нажал другую кнопку в msg {message_id}. "
                        f"Payload обновлен на свежий, таймер сдвинут на +{delay}с"
                    )
            else:
                # Достигли max_wait — форсируем обработку, больше не двигаем таймер
                exists = await redis_client.zscore(zset_key, task_id)
                if exists is None:
                    await redis_client.zadd(zset_key, {task_id: now})
                    logger.warning(f"⚠️ [Queue] Предел max_wait ({max_wait}с) достигнут для {task_id}. Встаем в очередь на отправку.")
                    
        return wrapper
    return decorator
