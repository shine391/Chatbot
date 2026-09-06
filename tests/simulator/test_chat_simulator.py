"""Unit tests running the ChatSimulator suite."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Category, Product
from tests.simulator.chat_simulator import ChatSimulator


class TestChatSimulatorExecution:
    @pytest.fixture
    async def seeded_simulator_db(self, db_session: AsyncSession) -> None:
        cat = Category(name="Túi da", slug="tui-da")
        db_session.add(cat)
        await db_session.flush()

        for i in range(1, 5):
            db_session.add(
                Product(
                    sku=f"SP00{i}",
                    name=f"Túi da bò chuẩn thương mại {i}",
                    price=1100000.0,
                    category_id=cat.id,
                    images=[f"https://shop.com/sp00{i}.jpg"],
                    website_url=f"https://shop.com/sp00{i}",
                    is_active=True,
                )
            )
        await db_session.flush()

    @pytest.mark.asyncio
    async def test_run_full_simulation_suite(
        self, db_session: AsyncSession, seeded_simulator_db: None
    ) -> None:
        sim = ChatSimulator()
        results = await sim.run_simulation(db_session)
        assert results["total"] == 4
        assert results["failed"] == 0
        assert results["passed"] == 4
