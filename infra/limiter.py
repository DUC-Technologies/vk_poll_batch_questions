import time

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
            {"key": "limiter:global", "max": 20, "rate": 20.0},                     # Глобальный ВК
            {"key": f"limiter:method:{method}", "max": 5, "rate": 5.0},            # Лимит на messages.edit
            {"key": f"limiter:user:{user_id}:{method}", "max": 2, "rate": 2.0},    # Лимит на юзера для edit
        ]
        
        # Получаем данные по всем корзинам за один проход
        pipe = self.redis.pipeline()
        for b in buckets:
            pipe.hgetall(b["key"])
        results = await pipe.execute()
        
        updates = {}
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
                return False  # Дефицит токенов в каскаде
                
            updates[b["key"]] = {"tokens": str(tokens - 1), "last_refill": str(now)}
            
        # Если все проверки прошли, атомарно списываем токены
        pipe = self.redis.pipeline()
        for key, mapping in updates.items():
            pipe.hset(key, mapping=mapping)
        await pipe.execute()
        
        return True
    