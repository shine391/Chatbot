"""Knowledge Base and Vector Store for customer service FAQ and policies."""


class KnowledgeStore:
    """In-memory and Chroma-compatible Knowledge Base for FAQ and shop policies."""

    def __init__(self) -> None:
        self.default_faqs: list[dict[str, str]] = [
            {
                "question": "Chính sách đổi trả hàng như thế nào?",
                "answer": "Shop hỗ trợ đổi trả miễn phí trong vòng 7 ngày kể từ khi nhận hàng nếu sản phẩm còn nguyên tem mác hoặc có lỗi từ nhà sản xuất.",
                "keywords": "đổi trả, hoàn tiền, lỗi sản phẩm, bảo hành",
            },
            {
                "question": "Thời gian giao hàng mất bao lâu?",
                "answer": "Nội thành giao nhanh trong 1-2 ngày, các tỉnh thành khác từ 2-4 ngày làm việc.",
                "keywords": "giao hàng, ship, thời gian nhận hàng, vận chuyển",
            },
            {
                "question": "Phí vận chuyển tính như thế nào?",
                "answer": "Miễn phí vận chuyển toàn quốc cho đơn hàng từ 500,000đ. Đơn dưới 500,000đ phí ship đồng giá 30,000đ.",
                "keywords": "phí ship, freeship, cước phí",
            },
            {
                "question": "Chính sách bảo hành sản phẩm đồ da?",
                "answer": "Tất cả sản phẩm đồ da thật được bảo hành bề mặt da và phụ kiện khóa kéo trong vòng 12 tháng.",
                "keywords": "bảo hành, da thật, bong tróc, phụ kiện",
            },
        ]

    def search_faq(self, query: str, top_k: int = 2) -> list[str]:
        """Search relevant FAQ answers by keyword relevance."""
        query_lower = query.lower()
        results: list[tuple[int, str]] = []

        for item in self.default_faqs:
            score = 0
            for kw in item["keywords"].split(", "):
                if kw in query_lower:
                    score += 2
            for word in query_lower.split():
                if len(word) > 2 and word in item["question"].lower():
                    score += 1

            if score > 0:
                results.append((score, f"Q: {item['question']}\nA: {item['answer']}"))

        results.sort(key=lambda x: x[0], reverse=True)
        if not results:
            # Fallback to general policy
            return [
                f"Q: {item['question']}\nA: {item['answer']}" for item in self.default_faqs[:top_k]
            ]
        return [r[1] for r in results[:top_k]]

    def add_knowledge(self, question: str, answer: str, keywords: str) -> None:
        """Add new entry to FAQ collection."""
        self.default_faqs.append({"question": question, "answer": answer, "keywords": keywords})

    def get_all_context_prompt(self) -> str:
        """Render entire store context for LLM prompt."""
        lines: list[str] = ["THÔNG TIN & CHÍNH SÁCH CỬA HÀNG:"]
        for f in self.default_faqs:
            lines.append(f"- {f['question']}: {f['answer']}")
        return "\n".join(lines)
