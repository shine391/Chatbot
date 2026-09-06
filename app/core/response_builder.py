"""Response builder module for formatting channel-appropriate rich cards and carousels."""

from typing import Any

from app.schemas.message import ChannelType, OutgoingMessage
from app.schemas.product import ProductCard, ProductDetail


class ResponseBuilder:
    """Builds standardized OutgoingMessage instances for different channels."""

    def format_price(self, price: float) -> str:
        """Format number as VND currency string (e.g. 1,200,000đ)."""
        return f"{int(price):,}đ"

    def build_product_detail_response(
        self,
        recipient_id: str,
        channel: ChannelType,
        product: ProductDetail,
    ) -> OutgoingMessage:
        """Build rich card response with image, description, price, and product link."""
        price_str = self.format_price(product.price)
        discount_str = (
            f" (Khuyến mãi: {self.format_price(product.discount_price)})"
            if product.discount_price
            else ""
        )

        content = (
            f"📦 Chi tiết sản phẩm: {product.name}\n"
            f"🔹 Mã SP: {product.sku}\n"
            f"💰 Giá: {price_str}{discount_str}\n"
            f"📝 Mô tả: {product.description or 'Sản phẩm cao cấp'}\n"
            f"🔗 Link đặt hàng: {product.website_url or 'Liên hệ shop'}"
        )

        product_card_dict: dict[str, Any] = {
            "sku": product.sku,
            "name": product.name,
            "price": product.price,
            "formatted_price": price_str,
            "image_url": product.images[0] if product.images else "",
            "website_url": product.website_url or "",
            "product_url": product.website_url or "",
        }

        return OutgoingMessage(
            recipient_id=recipient_id,
            channel=channel,
            content=content,
            media_urls=product.images[:1],
            message_type="product_card",
            products=[product_card_dict],
            quick_replies=["Tư vấn đặt hàng", "Xem mẫu khác", "Gặp nhân viên"],
        )

    def build_catalog_carousel_response(
        self,
        recipient_id: str,
        channel: ChannelType,
        category_name: str,
        products: list[ProductCard],
    ) -> OutgoingMessage:
        """Build 3-4 item catalog carousel response for browsing."""
        # Ensure between 1 and 4 products
        selected_products = products[:4]

        content = f"✨ Dạ đây là các mẫu {category_name} hot nhất bên shop gửi bạn tham khảo:\n"
        for idx, p in enumerate(selected_products, start=1):
            price_str = (
                self.format_price(p.discount_price)
                if p.discount_price
                else self.format_price(p.price)
            )
            content += f"{idx}. {p.name} - {price_str} (Mã: {p.sku})\n"

        content += "👉 Bạn thích mẫu nào hoặc cần mã sản phẩm nào nhắn shop gửi chi tiết nhé!"

        products_data: list[dict[str, Any]] = [
            {
                "sku": p.sku,
                "name": p.name,
                "price": p.price,
                "formatted_price": self.format_price(p.price),
                "image_url": p.image_url or "",
                "website_url": p.website_url or p.product_url or "",
                "product_url": p.product_url or p.website_url or "",
            }
            for p in selected_products
        ]

        media_urls = [p.image_url for p in selected_products if p.image_url]

        return OutgoingMessage(
            recipient_id=recipient_id,
            channel=channel,
            content=content,
            media_urls=media_urls[:4],
            message_type="carousel",
            products=products_data,
            quick_replies=[f"Mã {p.sku}" for p in selected_products] + ["Xem danh mục khác"],
        )

    def build_escalation_response(
        self,
        recipient_id: str,
        channel: ChannelType,
        reason: str,
    ) -> OutgoingMessage:
        """Build handover message when escalating to human agent."""
        content = (
            "Dạ shop đã ghi nhận yêu cầu của bạn! 👨‍💼 "
            "Nhân viên hỗ trợ sẽ liên hệ với bạn trong giây lát qua tin nhắn này ạ. "
            "Xin lỗi vì sự bất tiện này!"
        )
        return OutgoingMessage(
            recipient_id=recipient_id,
            channel=channel,
            content=content,
            message_type="text",
            quick_replies=["Tôi muốn đợi", "Hỏi câu khác"],
        )
