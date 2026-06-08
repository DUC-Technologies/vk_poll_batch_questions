import json
import time
from functools import wraps

TASK_REGISTRY = {}

def redis_debounce_queue(redis_client, name, delay=0.3, max_wait=1.0):
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
            
            status = state.get(b'status') or state.get('status')
            is_processing = status in (b'processing', 'processing')
            
            if is_processing:
                await redis_client.hdel(hash_key, 'status')
                first_click_at = now
                await redis_client.hset(hash_key, 'first_click_at', str(now))
            else:
                fc_val = state.get(b'first_click_at') or state.get('first_click_at')
                if fc_val:
                    first_click_at = float(fc_val)
                else:
                    first_click_at = now
                    await redis_client.hset(hash_key, 'first_click_at', str(now))
            
            await redis_client.hset(hash_key, 'payload', json.dumps(click_data))
            
            if (now - first_click_at) < max_wait:
                score = now + delay
                await redis_client.zadd(zset_key, {task_id: score})
            else:
                exists = await redis_client.zscore(zset_key, task_id)
                if exists is None:
                    await redis_client.zadd(zset_key, {task_id: now})
                    
        return wrapper
    return decorator
