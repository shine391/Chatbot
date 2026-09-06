# AI Customer Service Agent - Hệ Thống Chăm Sóc Khách Hàng Đa Kênh

Hệ thống AI Agent chăm sóc khách hàng thông minh được xây dựng **100% bằng Python**, sẵn sàng triển khai thương mại cho các cửa hàng và doanh nghiệp bán lẻ.

---

## 🌟 1. Tính Năng Nổi Bật

1. **Tiếp Nhận Đa Kênh Hợp Nhất (Omnichannel Inbox)**:
   - **Facebook Messenger** (Meta Graph API v21.0 - Generic Template, Buttons, Quick Replies).
   - **Instagram Direct Messages** (Meta Graph API - DM, Media attachments).
   - **TikTok Shop & Comment API** (Xử lý tin nhắn khách hàng & phản hồi bình luận).
   - **Website Live Chat** (REST/WebSocket API tích hợp trực tiếp vào website bán hàng).

2. **Tư Vấn Sản Phẩm Thông Minh (AI Powered by Google Gemini)**:
   - Tra cứu và phản hồi thông tin sản phẩm tức thì theo **mã SKU** (giá niêm yết, giá khuyến mãi, thông số, tồn kho).
   - Gửi kèm trực tiếp **hình ảnh, video** minh họa sắc nét và **đường link xem chi tiết** trên website.
   - Phản hồi danh mục sản phẩm (Catalogue) dưới dạng **Carousel chuẩn 3 - 4 sản phẩm** kèm nút bấm mua hàng.

3. **Chăm Sóc Khách Hàng Sau Bán & Tự Động Upsell (Post-Sale Care)**:
   - Tự động theo dõi các đơn hàng giao thành công (`DELIVERED`).
   - Sau đúng **7 ngày**, hệ thống tự động kích hoạt kịch bản chăm sóc: hỏi thăm mức độ hài lòng, gửi kèm **Carousel gợi ý 3 - 4 phụ kiện / sản phẩm nâng cấp liên quan**, kèm voucher ưu đãi giảm giá 10%.
   - Ghi nhận lịch sử và đánh dấu đơn hàng đã được chăm sóc để tránh làm phiền khách.

4. **Bộ Chuyển Tiếp Khiếu Nại & Hỗ Trợ Khẩn Cấp (Staff Escalation)**:
   - Tự động phát hiện cảm xúc tiêu cực, phản ánh sự cố kỹ thuật hoặc yêu cầu gặp người thật.
   - Bắn thông báo cảnh báo tức thì tới nhóm hỗ trợ viên qua **Telegram Bot** hoặc **Facebook Messenger CS**.

5. **Bộ Công Cụ Kiểm Thử Thương Mại & Gatekeeper**:
   - **Interactive Chat Simulator** (`tests/simulator/chat_simulator.py`): Giả lập trực tiếp các kịch bản thực tế từ người dùng đa kênh trước khi bàn giao cho đối tác.
   - **Gatekeeper Runner** (`scripts/evaluate_project.py`): Đảm bảo mã nguồn đạt 100% chuẩn tĩnh (`ruff`), an toàn kiểu nghiêm ngặt (`mypy --strict`), và vượt qua 100% kịch bản kiểm thử (`pytest`).

---
## 🛡️ Bản Quyền & Giấy Phép
Dự án được thiết kế chuyên biệt cho hoạt động kinh doanh thương mại điện tử đa kênh, tuân thủ tiêu chuẩn an toàn bảo mật dữ liệu khách hàng.
