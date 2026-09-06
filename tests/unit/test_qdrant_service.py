"""Unit tests for QdrantVectorService."""

import pytest

from app.knowledge.qdrant_service import QdrantVectorService


@pytest.fixture
def qdrant_service() -> QdrantVectorService:
    """Create an in-memory QdrantVectorService instance for fast and isolated unit tests."""
    return QdrantVectorService(location=":memory:")


def test_ensure_collection(qdrant_service: QdrantVectorService) -> None:
    """Test creating and checking collections in Qdrant."""
    collection_name = "test_collection"
    qdrant_service.ensure_collection(collection_name, vector_size=4)
    assert qdrant_service.collection_exists(collection_name) is True


def test_upsert_and_search_vectors(qdrant_service: QdrantVectorService) -> None:
    """Test upserting points and performing vector similarity search."""
    collection_name = "faq_test"
    qdrant_service.ensure_collection(collection_name, vector_size=3)

    points = [
        {
            "id": 1,
            "vector": [1.0, 0.0, 0.0],
            "payload": {
                "question": "Chính sách đổi trả hàng như thế nào?",
                "answer": "Shop hỗ trợ đổi trả trong 7 ngày.",
                "category": "policy",
            },
        },
        {
            "id": 2,
            "vector": [0.0, 1.0, 0.0],
            "payload": {
                "question": "Thời gian giao hàng mất bao lâu?",
                "answer": "Nội thành giao trong 1-2 ngày.",
                "category": "shipping",
            },
        },
    ]

    qdrant_service.upsert_points(collection_name, points)

    # Query closest to point 1
    results = qdrant_service.search(
        collection_name=collection_name,
        query_vector=[0.9, 0.1, 0.0],
        limit=1,
    )

    assert len(results) == 1
    assert results[0]["id"] == 1
    assert results[0]["payload"]["category"] == "policy"


def test_search_with_filter(qdrant_service: QdrantVectorService) -> None:
    """Test vector search with metadata payload filtering."""
    collection_name = "products_test"
    qdrant_service.ensure_collection(collection_name, vector_size=2)

    points = [
        {
            "id": 1,
            "vector": [0.5, 0.5],
            "payload": {"name": "Túi da công sở", "category": "tui-da", "price": 850000},
        },
        {
            "id": 2,
            "vector": [0.5, 0.5],
            "payload": {"name": "Ví da nam", "category": "vi-da", "price": 450000},
        },
    ]
    qdrant_service.upsert_points(collection_name, points)

    # Filter only vi-da
    results = qdrant_service.search(
        collection_name=collection_name,
        query_vector=[0.5, 0.5],
        limit=2,
        filter_key="category",
        filter_value="vi-da",
    )

    assert len(results) == 1
    assert results[0]["payload"]["name"] == "Ví da nam"
