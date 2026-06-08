import asyncio
import logging
from bot import bot, redis_client
from infra import run_queue_worker, CascadeRateLimiter


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-7s | %(asctime)s | %(name)s > %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

async def main(): 
    rate_limiter = CascadeRateLimiter(redis_client)
    worker_task = asyncio.create_task(
        run_queue_worker(redis_client, name="edit_keyboard", rate_limiter=rate_limiter)
    )
    
    logging.info("🚀 Инфраструктурный комплекс и каскадные лимиты успешно инициализированы.")
    
    print("Worker and Limiter has been started...")
    
    try:
        await bot.run_polling()
    finally:
        worker_task.cancel()
        await redis_client.close()

if __name__ == "__main__":
    asyncio.run(main())
    