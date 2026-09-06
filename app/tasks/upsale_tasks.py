"""Background tasks and job schedulers."""

import asyncio

from loguru import logger

from app.database.session import get_session_factory
from app.services.upsale_service import UpsaleService


async def run_upsale_campaign_job() -> int:
    """Scheduled task executing the 7-day post-sale care campaign."""
    logger.info("Executing scheduled post-sale upsell check...")
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = UpsaleService(session)
        sent = await service.check_and_trigger_upsales()
        await session.commit()
        logger.info(f"Post-sale campaign completed. Sent {sent} follow-ups.")
        return sent


def trigger_upsale_campaign_sync() -> int:
    """Synchronous entry point for cron / task schedulers."""
    return asyncio.run(run_upsale_campaign_job())


if __name__ == "__main__":
    count = trigger_upsale_campaign_sync()
    print(f"Upsell campaign run finished: {count} messages dispatched.")
