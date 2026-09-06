"""Unit tests for Sales Funnel CRM Engine and Customer Management API."""

import pytest
from httpx import AsyncClient

from app.models.customer import FunnelStage
from app.services.funnel_service import FunnelService


class TestFunnelService:
    def test_progression_detection_logic(self) -> None:
        """Test keyword-based funnel stage transitions."""
        # 1. New greeting message stays LEAD
        assert (
            FunnelService.detect_funnel_progression("Xin chào shop", FunnelStage.LEAD.value)
            == FunnelStage.LEAD.value
        )

        # 2. Inquiring about catalog/price promotes to INTERESTED
        assert (
            FunnelService.detect_funnel_progression(
                "Cho mình xem mẫu ví da với giá bao nhiêu ạ?", FunnelStage.LEAD.value
            )
            == FunnelStage.INTERESTED.value
        )

        # 3. High intent (shipping, payment, ordering) promotes to INTENT
        assert (
            FunnelService.detect_funnel_progression(
                "Cho mình số tài khoản để chuyển khoản nhé", FunnelStage.INTERESTED.value
            )
            == FunnelStage.INTENT.value
        )
        assert (
            FunnelService.detect_funnel_progression(
                "Ship về Cầu Giấy Hà Nội mất bao lâu?", FunnelStage.LEAD.value
            )
            == FunnelStage.INTENT.value
        )

        # 4. Purchased and loyal customers are not demoted
        assert (
            FunnelService.detect_funnel_progression("Chào bạn", FunnelStage.PURCHASED.value)
            == FunnelStage.PURCHASED.value
        )
        assert (
            FunnelService.detect_funnel_progression("Xem thêm mẫu", FunnelStage.LOYAL.value)
            == FunnelStage.LOYAL.value
        )


class TestCustomerCRMAPI:
    @pytest.mark.asyncio
    async def test_funnel_stats_and_customer_crud(self, app_client: AsyncClient) -> None:
        """Test customer listing, funnel stats, and manual stage updating."""
        # 1. Send webhook message to create a customer via website chat
        chat_payload = {
            "session_id": "cust_funnel_test_001",
            "content": "Cho mình xem mẫu túi da công sở với",
        }
        res_msg = await app_client.post("/webhook/website", json=chat_payload)
        assert res_msg.status_code == 200

        # 2. List customers and verify customer was created with INTERESTED stage
        res_custs = await app_client.get("/api/admin/customers")
        assert res_custs.status_code == 200
        cust_data = res_custs.json()
        cust_list = (
            cust_data["items"]
            if isinstance(cust_data, dict) and "items" in cust_data
            else cust_data
        )
        assert len(cust_list) >= 1

        target = next(
            (c for c in cust_list if c["platform_user_id"] == "cust_funnel_test_001"), None
        )
        assert target is not None
        cust_id = target["id"]
        assert target["funnel_stage"] == FunnelStage.INTERESTED.value

        # 3. Check funnel stats
        res_stats = await app_client.get("/api/admin/customers/funnel-stats")
        assert res_stats.status_code == 200
        stats = res_stats.json()
        assert stats["total_customers"] >= 1
        interested_stage = next(s for s in stats["stages"] if s["stage"] == "interested")
        assert interested_stage["count"] >= 1

        # 4. Update customer stage and add internal note
        update_payload = {
            "name": "Nguyễn Thị Mai",
            "phone": "0988776655",
            "funnel_stage": "intent",
            "notes": "Khách quan tâm mẫu TUI-01, thích màu nâu socola",
            "address": "456 Kim Mã, Ba Đình, Hà Nội",
        }
        res_up = await app_client.put(f"/api/admin/customers/{cust_id}", json=update_payload)
        assert res_up.status_code == 200
        updated = res_up.json()
        assert updated["name"] == "Nguyễn Thị Mai"
        assert updated["phone"] == "0988776655"
        assert updated["funnel_stage"] == "intent"
        assert updated["notes"] == "Khách quan tâm mẫu TUI-01, thích màu nâu socola"

        # 5. Get customer 360 detail
        res_detail = await app_client.get(f"/api/admin/customers/{cust_id}")
        assert res_detail.status_code == 200
        detail = res_detail.json()
        assert detail["customer"]["id"] == cust_id
        assert len(detail["conversations"]) >= 1
