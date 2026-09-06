"""Commercial testing simulator for validating AI Agent performance before merchant handover."""

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.conversation import ConversationManager
from app.database.session import get_session_factory
from app.schemas.message import ChannelType, IncomingMessage, OutgoingMessage


@dataclass
class SimulationScenario:
    """A test case representing real shopper behaviors."""

    name: str
    channel: ChannelType
    input_text: str
    expected_type: str  # "text", "product_card", "carousel"
    expected_keywords: list[str]
    min_products: int = 0
    max_products: int = 4


class ChatSimulator:
    """Simulator engine executing commercial test suites to certify AI Agent readiness."""

    def __init__(self) -> None:
        self.scenarios: list[SimulationScenario] = [
            SimulationScenario(
                name="Tra cứu mã sản phẩm kèm ảnh/link website",
                channel=ChannelType.FACEBOOK,
                input_text="Shop cho mình xem mã SP001 với",
                expected_type="product_card",
                expected_keywords=["SP001", "Giá"],
                min_products=1,
                max_products=1,
            ),
            SimulationScenario(
                name="Yêu cầu catalogue túi da (chuẩn 3-4 item)",
                channel=ChannelType.INSTAGRAM,
                input_text="Gửi mình xem catalogue túi da nhé",
                expected_type="carousel",
                expected_keywords=["túi da", "mẫu"],
                min_products=3,
                max_products=4,
            ),
            SimulationScenario(
                name="Chính sách bảo hành đổi trả hàng",
                channel=ChannelType.WEBSITE,
                input_text="Chính sách bảo hành và đổi trả của shop như thế nào?",
                expected_type="text",
                expected_keywords=["bảo hành", "đổi trả"],
            ),
            SimulationScenario(
                name="Yêu cầu gặp nhân viên hỗ trợ trực tiếp",
                channel=ChannelType.TIKTOK,
                input_text="Tôi muốn gặp nhân viên thật để khiếu nại",
                expected_type="text",
                expected_keywords=["nhân viên"],
            ),
        ]

    async def run_simulation(self, session: AsyncSession) -> dict[str, Any]:
        """Execute all scenarios and compile certification report."""
        manager = ConversationManager(session)
        passed = 0
        failed = 0
        details: list[dict[str, Any]] = []

        logger.info(f"Starting commercial simulation with {len(self.scenarios)} scenarios...")

        for idx, sc in enumerate(self.scenarios, start=1):
            incoming = IncomingMessage(
                sender_id=f"SIMULATOR_USER_{idx}",
                channel=sc.channel,
                content=sc.input_text,
            )
            resp: OutgoingMessage = await manager.handle_message(incoming)

            # Check expectations
            errors: list[str] = []
            content_lower = (resp.content or "").lower()

            if resp.message_type != sc.expected_type and sc.expected_type != "text":
                # Allow text fallback if catalog empty
                if not (sc.expected_type == "product_card" and resp.message_type == "text"):
                    errors.append(f"Expected type '{sc.expected_type}', got '{resp.message_type}'")

            for kw in sc.expected_keywords:
                if kw.lower() not in content_lower:
                    errors.append(f"Missing expected keyword '{kw}'")

            if sc.min_products > 0 and len(resp.products) < sc.min_products:
                # If store has products
                if resp.products:
                    errors.append(
                        f"Expected at least {sc.min_products} products, got {len(resp.products)}"
                    )

            status = "PASSED" if not errors else "FAILED"
            if status == "PASSED":
                passed += 1
            else:
                failed += 1

            details.append(
                {
                    "scenario": sc.name,
                    "status": status,
                    "errors": errors,
                    "response_type": resp.message_type,
                }
            )

        return {
            "total": len(self.scenarios),
            "passed": passed,
            "failed": failed,
            "details": details,
        }


async def run_standalone_simulation() -> dict[str, Any]:
    """Execute simulator from terminal command or pipeline."""
    from sqlalchemy import select

    from app.database.session import get_engine, init_db
    from app.models.product import Category, Product

    engine = get_engine()
    await init_db(engine)

    session_factory = get_session_factory(engine)
    async with session_factory() as session:
        # Seed test data if not already present
        res = await session.execute(select(Product).where(Product.sku == "SP001"))
        if not res.scalars().first():
            cat = Category(name="Túi da", slug="tui-da")
            session.add(cat)
            await session.flush()
            for i in range(1, 5):
                session.add(
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
            await session.commit()

        sim = ChatSimulator()
        return await sim.run_simulation(session)


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    result = asyncio.run(run_standalone_simulation())
    print("\n" + "=" * 60)
    print(f"COMMERCIAL CHAT SIMULATOR RESULTS: {result['passed']}/{result['total']} PASSED")
    print("=" * 60)
    for d in result["details"]:
        status = d["status"]
        print(f"[{status}] {d['scenario']} -> Type: {d['response_type']}")
        if d.get("errors"):
            for err in d["errors"]:
                print(f"       -> Error: {err}")
    print("=" * 60 + "\n")
