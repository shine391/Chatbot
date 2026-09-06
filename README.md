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

## 🏗️ 2. Cấu Trúc Dự Án

```
├── app/
│   ├── api/                    # API Endpoints
│   │   ├── admin.py            # Dashboard thống kê & CRUD Sản phẩm/Danh mục
│   │   ├── health.py           # Health check endpoint
│   │   └── webhooks/           # Bộ thu nhận Webhook từ Facebook, Instagram, TikTok, Website
│   ├── channels/               # Channel Adapters (Meta Graph, TikTok, Website)
│   ├── core/                   # Bộ xử lý cốt lõi
│   │   ├── ai_engine.py        # Gemini AI Engine tích hợp RAG
│   │   ├── conversation.py     # Conversation Manager (Quản lý ngữ cảnh)
│   │   ├── intent_detector.py  # Phân loại ý định, bóc tách SKU & danh mục
│   │   ├── interfaces.py       # Abstract Base Classes (Chuẩn kiến trúc phần mềm)
│   │   └── response_builder.py # Xây dựng thẻ sản phẩm đơn lẻ & Carousel 3-4 items
│   ├── database/               # Quản lý kết nối Async SQLAlchemy
│   ├── knowledge/              # Vector Store lưu FAQ, chính sách đổi trả & bảo hành
│   ├── models/                 # ORM Models: Customer, Conversation, Message, Product, Order
│   ├── schemas/                # Pydantic Schemas xác thực dữ liệu đầu vào/ra
│   ├── services/               # Catalog, Media, Message Routing, Upsale, Escalation
│   └── tasks/                  # Cronjob & Background tasks (quét đơn hàng 7 ngày upsell)
├── scripts/
│   └── evaluate_project.py     # Script Gatekeeper tự động kiểm định dự án
├── tests/
│   ├── integration/            # Test tích hợp luồng đời khách hàng (E2E)
│   ├── simulator/              # Trình giả lập giao tiếp với bot cho shop nghiệm thu
│   └── unit/                   # Test độc lập từng module (Channels, AI, Services, Admin)
├── Dockerfile                  # Container đóng gói sản phẩm
├── docker-compose.yml          # Triển khai nhanh API + Redis
├── requirements.txt            # Danh sách thư viện Python
└── pyproject.toml              # Cấu hình linter, test runner, typing
```

---

## 🚀 3. Hướng Dẫn Cài Đặt & Chạy Môi Trường Local

### Yêu cầu hệ thống:
- Python 3.12 hoặc 3.14
- Git

### Bước 1: Tạo môi trường ảo và cài đặt thư viện
```bash
# Clone repository hoặc mở thư mục dự án
cd "Project Chatbot"

# Khởi tạo virtual environment
python -m venv venv

# Kích hoạt môi trường (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Cài đặt toàn bộ thư viện cần thiết
pip install -r requirements.txt
```

### Bước 2: Thiết lập biến môi trường
Tạo file `.env` từ file `.env.example`:
```bash
cp .env.example .env
```
Mở file `.env` và điền các thông tin quan trọng:
```ini
# Google Gemini API (Lấy miễn phí tại Google AI Studio)
GEMINI_API_KEY=AIzaSy...

# Cấu hình Meta (Facebook & Instagram)
FACEBOOK_PAGE_ACCESS_TOKEN=EAA...
FACEBOOK_APP_SECRET=abc123...
FACEBOOK_VERIFY_TOKEN=my_custom_secure_verify_token_2026
INSTAGRAM_PAGE_ACCESS_TOKEN=EAA...

# Cấu hình TikTok
TIKTOK_APP_KEY=your_key
TIKTOK_APP_SECRET=your_secret
TIKTOK_ACCESS_TOKEN=your_token

# Cấu hình Cảnh báo nhân viên (Escalation)
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=-100123456789
```

### Bước 3: Khởi động Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
- API Docs (Swagger UI): `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`
- Admin Dashboard Stats: `http://localhost:8000/api/admin/dashboard/stats`

---

## 🐳 4. Triển Khai Bằng Docker & Docker Compose

Để chạy toàn bộ hệ thống (FastAPI Bot + Redis) ở môi trường Production:

```bash
# Build và chạy ngầm các container
docker compose up -d --build

# Xem log hoạt động của Bot
docker compose logs -f chatbot-api

# Kiểm tra trạng thái các container
docker compose ps

# Dừng hệ thống
docker compose down
```

---

## 🌐 5. Hướng Dẫn Cấu Hình Webhook Đa Kênh

Khi phát triển ở máy cá nhân hoặc kiểm thử trước khi bàn giao, sử dụng `ngrok` để mở port công khai ra Internet:
```bash
ngrok http 8000
```
Giả sử bạn nhận được đường dẫn: `https://abc-123.ngrok-free.app`.

### 5.1. Cấu hình Facebook Messenger Webhook
1. Truy cập [Meta for Developers](https://developers.facebook.com/) -> Chọn Ứng dụng của bạn -> Thêm sản phẩm **Messenger**.
2. Tại mục **Webhooks**:
   - **Callback URL**: `https://abc-123.ngrok-free.app/webhook/facebook`
   - **Verify Token**: Nhập đúng chuỗi đã khai báo tại `FACEBOOK_VERIFY_TOKEN` trong `.env`.
   - Nhấn **Verify and Save**.
3. Tại phần **Subscription Fields**: Chọn tích các sự kiện: `messages`, `messaging_postbacks`, `message_deliveries`.
4. Gắn Webhook vào Fanpage của bạn trong phần **Select a Page**.

### 5.2. Cấu hình Instagram Direct Messages
1. Trong cài đặt ứng dụng Meta Developers, thêm sản phẩm **Instagram Graph API**.
2. Liên kết tài khoản Instagram Chuyên nghiệp (Business/Creator) với Facebook Page.
3. Cấu hình Webhook:
   - **Callback URL**: `https://abc-123.ngrok-free.app/webhook/instagram`
   - **Verify Token**: Sử dụng cùng token bảo mật đã cấu hình.
   - Đăng ký nhận sự kiện `messages`.

### 5.3. Cấu hình TikTok Shop & Comment API
1. Đăng ký tài khoản nhà phát triển tại [TikTok Shop Partner Center](https://partner.tiktokshop.com/).
2. Tạo App dịch vụ khách hàng (Customer Service Application).
3. Đăng ký Webhook nhận sự kiện chat:
   - **Webhook URL**: `https://abc-123.ngrok-free.app/webhook/tiktok`
   - Tải về `App Key` và `App Secret` điền vào `.env`.

### 5.4. Tích hợp Website Live Chat
Website có thể gửi nhận tin nhắn trực tiếp qua REST API:
- **Gửi tin nhắn**: `POST /api/chat/send`
  ```json
  {
    "session_id": "user_session_abc",
    "content": "Cho mình xem catalogue túi xách",
    "media_urls": []
  }
  ```
- **Lấy lịch sử hội thoại**: `GET /api/chat/history/{session_id}`

---

## 🧪 6. Kiểm Thử Trước Khi Đưa Vào Thương Mại

Trước khi bàn giao bot cho chủ shop hoặc vận hành thực tế, hệ thống cung cấp 2 cơ chế kiểm soát chất lượng tuyệt đối:

### 6.1. Trình Giả Lập Thương Mại (Commercial Chat Simulator)
Chạy script tương tác mô phỏng người dùng nhắn tin qua các kênh Facebook, TikTok, Instagram hoặc Web:
```bash
python tests/simulator/chat_simulator.py
```
**Các kịch bản tự động có sẵn để kiểm tra:**
- Nhắn mã sản phẩm: `"Cho mình xem túi DA01"` -> Bot trả về tên, giá kèm ảnh sắc nét và nút xem link web.
- Hỏi theo danh mục: `"Shop có những mẫu túi nào?"` -> Bot lập tức xuất Carousel 3 - 4 mẫu túi nổi bật kèm ảnh và giá.
- Khiếu nại dịch vụ: `"Sản phẩm bị lỗi rách chỉ, thái độ tệ quá"` -> Bot xoa dịu và kích hoạt báo động escalation tới Telegram nhân viên.
- Chế độ tự gõ tương tác tự do (Interactive Mode).

### 6.2. Kiểm Định Chất Lượng Tự Động (Gatekeeper Runner)
Chạy bộ kiểm thử toàn diện 3 tầng:
```bash
python scripts/evaluate_project.py
```
Quy trình sẽ tự động thực thi tuần tự:
1. `ruff check app/ tests/` (Bắt sạch lỗi cú pháp, biến thừa, import sai).
2. `mypy --strict app/` (Xác thực kiểu tĩnh 100% nghiêm ngặt, triệt tiêu lỗi Runtime).
3. `pytest tests/` (Chạy toàn bộ hơn 137 unit và integration test).
Chỉ khi tất cả đều đạt chuẩn (Exit Code 0), hệ thống mới đạt chứng chỉ triển khai thương mại.

---

## ⏰ 7. Vận Hành Tác Vụ Chăm Sóc Sau Bán & Upsale (7 Ngày)

Để kích hoạt quét cơ sở dữ liệu và gửi thông điệp chăm sóc kèm gợi ý sản phẩm phụ kiện cho những khách hàng đã nhận hàng sau 7 ngày:

### Chạy thủ công:
```bash
python -m app.tasks.upsale_tasks
```

### Cấu hình tự động định kỳ (Crontab trên Linux / VPS):
Để hệ thống tự động quét mỗi ngày 1 lần vào lúc 09:00 sáng, thêm dòng sau vào `crontab -e`:
```bash
0 9 * * * cd /path/to/Project_Chatbot && ./venv/bin/python -m app.tasks.upsale_tasks >> /var/log/upsale_cron.log 2>&1
```

---

## 📊 8. Admin Center & Quản Trị Toàn Diện (Phases 10 - 13)

Hệ thống cung cấp trọn vẹn trung tâm điều hành chuyên nghiệp:
- **Xác thực & Bảo mật (Phase 10)**: JWT authentication, bcrypt hashing, single-flight refresh token interceptor, WebSocket token verification (`WS_1008`).
- **Hạ Tầng Dual DB & Sao Lưu Trực Tuyến (Phase 11)**:
  - Hỗ trợ tương thích đồng thời SQLite và PostgreSQL với connection pooling chuẩn (`pool_size=10, max_overflow=20, pool_pre_ping=True, pool_recycle=3600`).
  - Tiện ích sao lưu atomic trực tuyến `scripts/backup_db.py` (SQLite Online Backup API + Qdrant Vector Collection Snapshots & JSON point manifests) và endpoint `POST /api/admin/system/backup`.
- **Phân Tích Dữ Liệu & Trực Quan Hóa Tương Tác (Phase 12)**:
  - Endpoint phân tích đa chiều `GET /api/admin/dashboard/analytics?days=7|30`: Biến động đơn hàng, lượng tin nhắn, phân bổ kênh khách hàng (Facebook, Instagram, TikTok, Website) và doanh thu theo ngày.
  - Biểu đồ tối ưu dark-mode với Chart.js (Line trends, Channels doughnut, Revenue bar).
  - Phân trang máy chủ & sắp xếp linh hoạt `PaginatedResponse[T]` cho Kho sản phẩm, CRM và Đơn hàng.
  - Xuất dữ liệu CSV chuẩn Excel UTF-8 BOM (`/api/admin/customers/export`, `/api/admin/orders/export`).
  - Điều hướng URL Hash liền mạch (`#dashboard`, `#crm`, `#orders`, `#products`, `#livechat`, `#settings`).
- **Hỗ Trợ Bán Hàng & Chăm Sóc Khách Thực Chiến (Phase 13)**:
  - Quản lý tin nhắn trả lời nhanh Quick Replies (`GET/POST/PUT/DELETE /api/admin/quick-replies`) kèm phím tắt shortcut và bộ chọn ngay tại khung chat Live Chat.
  - Trung tâm thông báo thời gian thực (Notification Center): chuông cảnh báo, dropdown lịch sử thông báo, đồng bộ tức thì qua WebSocket khi có đơn hàng mới hoặc sự kiện can thiệp.
  - Quản lý nhãn khách hàng chuyên sâu (Customer Tagging): gắn nhãn VIP, bom hàng, cần tư vấn thêm, khách sỉ... hiển thị trực tiếp trên thẻ hồ sơ 360° và bảng CRM.

---

## 🛡️ Bản Quyền & Giấy Phép
Dự án được thiết kế chuyên biệt cho hoạt động kinh doanh thương mại điện tử đa kênh, tuân thủ tiêu chuẩn an toàn bảo mật dữ liệu khách hàng.
