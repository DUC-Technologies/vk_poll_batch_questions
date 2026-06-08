import time
import logging

logger = logging.getLogger("infra.limiter")

class CascadeRateLimiter:
    """
    Управляет каскадными лимитами запросов через Redis Token Bucket.
    Три типа лимитов сделал. Глобальный, глобальный на edit, индивидуальный на edit у юзера.
    """
    def __init__(self, redis_client):
        self.redis = redis_client

    async def check_and_consume(self, user_id: str, method: str) -> bool:
        now = time.time()
        
        buckets = [
            {"name": "Глобальный ВК", "key": "limiter:global", "max": 20, "rate": 20.0},
            {"name": "Лимит Метода", "key": f"limiter:method:{method}", "max": 5, "rate": 5.0},
            {"name": "Лимит Юзера", "key": f"limiter:user:{user_id}:{method}", "max": 2, "rate": 1.0},
        ]
        
        # Получаем данные по всем корзинам за один проход
        pipe = self.redis.pipeline()
        for b in buckets:
            pipe.hgetall(b["key"])
        results = await pipe.execute()
        
        updates = {}
        bucket_status_logs = []
        
        for idx, b in enumerate(buckets):
            data = results[idx]
            t_key = b'tokens' if b'tokens' in data else 'tokens'
            r_key = b'last_refill' if b'last_refill' in data else 'last_refill'
            
            if not data or t_key not in data:
                tokens = b["max"]
                last_refill = now
            else:
                last_refill = float(data[r_key])
                passed_time = now - last_refill
                tokens = min(b["max"], float(data[t_key]) + passed_time * b["rate"])
            
            if tokens < 1:
                logger.warning(
                    f"❌ [RateLimiter] БЛОКИРОВКА! Нарушен '{b['name']}'. "
                    f"Остаток токенов: {tokens:.2f} (требуется >= 1.0) | Юзер: {user_id}"
                )
                return False  # Дефицит токенов в каскаде
                
            new_tokens = tokens - 1
            updates[b["key"]] = {"tokens": str(new_tokens), "last_refill": str(now)}
            bucket_status_logs.append(f"{b['name']}: {int(new_tokens)}/{b['max']}")
            
        # Если все проверки прошли, атомарно списываем токены
        pipe = self.redis.pipeline()
        for key, mapping in updates.items():
            pipe.hset(key, mapping=mapping)
        await pipe.execute()
        
        logger.info(f"📊 [RateLimiter] Токен списан успешно. Бакеты -> \n - {'\n - '.join(bucket_status_logs)}")
        return True
    