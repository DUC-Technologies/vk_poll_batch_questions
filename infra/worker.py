"""
Чтобы воркер в случае успеха не удалил новые клики, которые прилетели во время его работы с сетью:
1. Когда хендлер кликов видит, что status == processing, он должен не просто дописать новые клики, 
он должен удалить поле status (или переписать его, например, на status = dirty), 
а также обновить first_click_at на текущее время, ведь началась новая серия.

2. Воркер должен удалять Хеш атомарно и только если там всё еще processing
В блоке «Успех» воркер не должен делать слепой DEL. Он должен удалить Хеш только в том случае, 
если за время его отсутствия никто не докинул новые клики (то есть поле status всё еще равно processing). 
"""

import asyncio
import time
import json
import logging
from .queue import TASK_REGISTRY

logger = logging.getLogger("infra.worker")

LUA_COMPARE_AND_DELETE = """
if redis.call('hget', KEYS[1], 'status') == 'processing' then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

async def run_queue_worker(redis_client, name, rate_limiter):
    """Асинхронный воркер очереди."""
    zset_key = f"queue:{name}"
    func = TASK_REGISTRY.get(name)
    
    while True:
        try:
            now = time.time()
            # Берем одну созревшую задачу
            tasks = await redis_client.zrangebyscore(zset_key, 0, now, start=0, num=1)
            
            if not tasks:
                await asyncio.sleep(0.05)
                continue
                
            task_id = tasks[0].decode() if isinstance(tasks[0], bytes) else tasks[0]
            user_id, message_id = task_id.split(':')
            hash_key = f"edit_state:{user_id}:{message_id}"
            
            # 1. Проверяем лимиты ДО удаления из очереди
            if not await rate_limiter.check_and_consume(user_id, "messages.edit"):
                logger.info(f"⏳ [Worker] Каскадный лимит исчерпан. Отодвигаем {task_id} на +0.5с")
                await redis_client.zadd(zset_key, {task_id: now + 0.5})
                continue
                
            # 2. Атомарно удаляем из ZSET, чтобы другие воркеры (если их несколько) не подхватили
            if not await redis_client.zrem(zset_key, task_id):
                continue
                
            # Переводим в статус обработки
            await redis_client.hset(hash_key, "status", "processing")
            
            state = await redis_client.hgetall(hash_key)
            p_val = state.get(b'payload') or state.get('payload')
            if not p_val:
                continue
                
            click_data = json.loads(p_val.decode() if isinstance(p_val, bytes) else p_val)
            
            try:
                logger.info(f"🚀 [Worker] Отправляем РЕЗУЛЬТАТ схлапывания в ВК для {task_id}...")
                
                # Выполняем messages.edit (передается самый ПОСЛЕДНИЙ сохраненный payload)
                await func(int(user_id), int(message_id), click_data)
                
                # Проверяем через Lua: не было ли новых кликов, пока мы ждали ВК?
                lua_result = await redis_client.eval(LUA_COMPARE_AND_DELETE, 1, hash_key)
                
                if lua_result == 0:
                    logger.info(f"🔄 [Worker] [Lua]: Пока мы отправляли запрос, юзер кликнул снова! Стейт сохранен для следующего кадра.")
                else:
                    logger.info(f"✨ [Worker] Задача {task_id} успешно доставлена, стейт очищен.")
                
            except Exception as e:
                logger.error(f"💥 [Worker] Ошибка API ВК для {task_id}: {e}")
                await redis_client.hdel(hash_key, "status")
                await redis_client.zadd(zset_key, {task_id: time.time() + 0.5})
                
        except Exception as ce:
            logger.critical(f"🚨 Критический сбой цикла воркера: {ce}")
            await asyncio.sleep(1)
