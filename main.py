import asyncio
from bot import bot, redis_client
from infra import run_queue_worker, CascadeRateLimiter
async def main(): 
    rate_limiter = CascadeRateLimiter(redis_client)
    worker_task = asyncio.create_task(
        run_queue_worker(redis_client, name="edit_keyboard", rate_limiter=rate_limiter)
    )
    
    print("Worker and Limiter has been started...")
    
    try:
        await bot.run_polling()
    finally:
        worker_task.cancel()
        await redis_client.close()

if __name__ == "__main__":
    asyncio.run(main())
    