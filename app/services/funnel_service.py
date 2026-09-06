"""Sales Funnel CRM Service for customer lifecycle tracking and conversion metrics."""

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer, FunnelStage
from app.models.order import Order
from app.schemas.customer import FunnelStageCount, FunnelStatsResponse

STAGE_LABELS = {
    FunnelStage.LEAD.value: "1. Tiềm năng mới (Lead)",
    FunnelStage.INTERESTED.value: "2. Đang quan tâm (Interested)",
    FunnelStage.INTENT.value: "3. Ý định mua cao (Intent)",
    FunnelStage.PURCHASED.value: "4. Đã mua hàng (Purchased)",
    FunnelStage.LOYAL.value: "5. Khách thân thiết (Loyal)",
    FunnelStage.LOST.value: "6. Rơi rớt / Cần Remarketing (Lost)",
}

# Regex keywords for intent detection
INTENT_KEYWORDS = re.compile(
    r"(ship|giao hàng|địa chỉ|thanh toán|chuyển khoản|stk|số tài khoản|chốt|lấy chiếc này|lấy mẫu này|mua mẫu|đặt hàng|gửi về|bán cho mình)",
    re.IGNORECASE,
)

INTERESTED_KEYWORDS = re.compile(
    r"(xem|giá|bao nhiêu|nhiêu tiền|màu|size|chất liệu|bảo hành|mẫu nào|tư vấn|sản phẩm|catalog|danh mục)",
    re.IGNORECASE,
)


class FunnelService:
    """Manages customer funnel progression and CRM segmentation."""

    @staticmethod
    def detect_funnel_progression(message_content: str | None, current_stage: str | None) -> str:
        """Analyze message content and determine if customer should advance in funnel."""
        stage = current_stage or FunnelStage.LEAD.value
        if not message_content:
            return stage

        # Once a customer has purchased or is loyal, do not downgrade to lead/interested
        if stage in (FunnelStage.PURCHASED.value, FunnelStage.LOYAL.value):
            return stage

        # Check for high buying intent
        if INTENT_KEYWORDS.search(message_content):
            return FunnelStage.INTENT.value

        # Check for general interest / product discovery
        if stage == FunnelStage.LEAD.value and INTERESTED_KEYWORDS.search(message_content):
            return FunnelStage.INTERESTED.value

        return stage

    @staticmethod
    async def update_customer_stage(
        session: AsyncSession,
        customer_id: int,
        new_stage: str,
        notes: str | None = None,
        address: str | None = None,
    ) -> Customer | None:
        """Update a customer's funnel stage and optional metadata."""
        stmt = select(Customer).where(Customer.id == customer_id)
        customer = (await session.execute(stmt)).scalar_one_or_none()
        if not customer:
            return None

        customer.funnel_stage = new_stage
        if notes is not None:
            customer.notes = notes
        if address is not None:
            customer.address = address

        await session.commit()
        await session.refresh(customer)
        return customer

    @staticmethod
    async def check_and_promote_after_order(
        session: AsyncSession,
        customer_id: int,
    ) -> Customer | None:
        """Promote customer to PURCHASED or LOYAL upon new order creation."""
        stmt_orders = select(func.count(Order.id)).where(Order.customer_id == customer_id)
        order_count = (await session.execute(stmt_orders)).scalar() or 0

        stmt_cust = select(Customer).where(Customer.id == customer_id)
        customer = (await session.execute(stmt_cust)).scalar_one_or_none()
        if not customer:
            return None

        if order_count >= 2:
            customer.funnel_stage = FunnelStage.LOYAL.value
        elif order_count >= 1:
            customer.funnel_stage = FunnelStage.PURCHASED.value

        await session.commit()
        await session.refresh(customer)
        return customer

    @staticmethod
    async def get_funnel_statistics(session: AsyncSession) -> FunnelStatsResponse:
        """Compute aggregate counts and conversion rates across all funnel stages."""
        total_stmt = select(func.count(Customer.id))
        total_customers = (await session.execute(total_stmt)).scalar() or 0

        # Query counts grouped by funnel_stage
        group_stmt = select(Customer.funnel_stage, func.count(Customer.id)).group_by(
            Customer.funnel_stage
        )
        rows = (await session.execute(group_stmt)).all()
        counts_dict: dict[str, int] = {stage.value: 0 for stage in FunnelStage}
        for stage_val, count in rows:
            if stage_val in counts_dict:
                counts_dict[stage_val] = count
            elif stage_val:
                counts_dict[stage_val] = count

        stages_result: list[FunnelStageCount] = []
        for stage_enum in FunnelStage:
            s_val = stage_enum.value
            c = counts_dict.get(s_val, 0)
            pct = round((c / total_customers * 100.0), 1) if total_customers > 0 else 0.0
            stages_result.append(
                FunnelStageCount(
                    stage=s_val,
                    label=STAGE_LABELS.get(s_val, s_val.capitalize()),
                    count=c,
                    percentage=pct,
                )
            )

        purchased_count = counts_dict.get(FunnelStage.PURCHASED.value, 0) + counts_dict.get(
            FunnelStage.LOYAL.value, 0
        )
        conversion_rate = (
            round((purchased_count / total_customers * 100.0), 2) if total_customers > 0 else 0.0
        )

        return FunnelStatsResponse(
            total_customers=total_customers,
            stages=stages_result,
            conversion_rate=conversion_rate,
        )
