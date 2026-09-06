"""Shipping Carrier Webhook Handler for GHTK, GHN, and Viettel Post."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.models.conversation import Conversation, Message, MessageRole, MessageType
from app.models.customer import Customer
from app.models.order import Order, OrderStatus
from app.services.message_sender import MessageSender
from app.services.shipping import get_shipping_carrier

router = APIRouter(prefix="/api/webhooks/shipping", tags=["shipping-webhooks"])


def _map_carrier_status(raw_status: str) -> tuple[OrderStatus | None, str]:
    """Map carrier-specific status string to internal OrderStatus and friendly text."""
    s = (raw_status or "").lower()

    if any(
        k in s
        for k in (
            "delivering",
            "delivering_order",
            "dang_giao",
            "picked",
            "in_transit",
            "transporting",
        )
    ):
        return OrderStatus.SHIPPED, "Đơn hàng đang trên đường giao tới bạn"
    elif any(k in s for k in ("delivered", "da_giao", "success", "completed", "done")):
        return OrderStatus.DELIVERED, "Giao hàng thành công"
    elif any(k in s for k in ("cancel", "huy", "returned", "tra_hang", "returning")):
        return OrderStatus.CANCELLED, "Đơn hàng đã hủy hoặc chuyển hoàn"

    return None, raw_status


@router.post("/{carrier}")
async def handle_shipping_webhook(
    carrier: str,
    request: Request,
    token: str | None = Header(None, alias="X-Carrier-Token"),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Receive shipping status webhook callbacks from logistics carriers."""
    carrier_adapter = get_shipping_carrier(carrier)

    try:
        body = await request.json()
    except Exception:
        body = {}

    auth_token = token or str(request.query_params.get("token", "")) or str(body.get("token", ""))
    if not carrier_adapter.verify_webhook_token(auth_token):
        logger.warning(f"Unauthorized shipping webhook callback for carrier '{carrier}'.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Mã xác thực Webhook không hợp lệ.",
        )

    # Extract tracking code and status
    tracking_code = (
        body.get("label_id")
        or body.get("OrderCode")
        or body.get("ORDER_NUMBER")
        or body.get("tracking_code")
        or body.get("order_code")
        or ""
    )
    raw_status = (
        body.get("status_id")
        or body.get("Status")
        or body.get("status")
        or body.get("ORDER_STATUS")
        or ""
    )
    status_text = body.get("status_text") or body.get("reason") or str(raw_status)

    if not tracking_code:
        return {"success": False, "message": "Missing tracking code in webhook"}

    # Find matching order
    stmt = select(Order).where(Order.tracking_code == tracking_code)
    order = (await session.execute(stmt)).scalar_one_or_none()
    if not order:
        logger.info(f"Shipping webhook received for unknown tracking code '{tracking_code}'")
        return {"success": False, "message": "Order not found for tracking code"}

    mapped_status, friendly_status = _map_carrier_status(str(raw_status))
    if mapped_status:
        order.status = mapped_status
        if mapped_status == OrderStatus.DELIVERED and not order.delivered_at:
            order.delivered_at = datetime.now(timezone.utc)

    order.carrier_status_text = status_text or friendly_status
    await session.commit()

    # Notify customer via channel
    try:
        cust_stmt = select(Customer).where(Customer.id == order.customer_id)
        customer = (await session.execute(cust_stmt)).scalar_one_or_none()

        if customer and mapped_status in (OrderStatus.SHIPPED, OrderStatus.DELIVERED):
            sender = await MessageSender.from_settings(session)
            if mapped_status == OrderStatus.SHIPPED:
                notify_msg = (
                    f"📦 Thông báo giao hàng: Đơn hàng #{order.id} của bạn đang được hãng {carrier.upper()} "
                    f"giao tới bạn (Mã vận đơn: {order.tracking_code})."
                )
            else:
                notify_msg = (
                    f"🎉 Chúc mừng bạn! Đơn hàng #{order.id} đã được giao thành công. "
                    "Shop cảm ơn bạn rất nhiều vì đã tin tưởng và ủng hộ shop! ❤️"
                )

            # Record in conversation
            conv_stmt = (
                select(Conversation)
                .where(Conversation.customer_id == customer.id)
                .order_by(Conversation.id.desc())
            )
            conv = (await session.execute(conv_stmt)).scalars().first()
            if conv:
                session.add(
                    Message(
                        conversation_id=conv.id,
                        role=MessageRole.BOT,
                        content=notify_msg,
                        message_type=MessageType.TEXT,
                    )
                )

            await sender.send_text(
                platform=str(customer.platform),
                recipient_id=customer.platform_user_id,
                text=notify_msg,
            )
            await session.commit()
    except Exception as exc:
        logger.warning(f"Could not dispatch shipping notification to customer: {exc}")

    return {
        "success": True,
        "order_id": order.id,
        "tracking_code": tracking_code,
        "status": order.status.value if hasattr(order.status, "value") else str(order.status),
        "status_text": order.carrier_status_text,
    }
