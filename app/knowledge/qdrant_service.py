"""Qdrant Vector Database service for semantic retrieval and RAG."""

from typing import Any

from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.config import get_settings


class QdrantVectorService:
    """Service wrapper for Qdrant Vector Search Engine."""

    def __init__(
        self,
        location: str | None = None,
        host: str | None = None,
        port: int | None = None,
        api_key: str | None = None,
    ) -> None:
        settings = get_settings()
        if location:
            self.client = QdrantClient(location=location)
        else:
            h = host or settings.qdrant_host
            p = port or settings.qdrant_port
            k = api_key if api_key is not None else (settings.qdrant_api_key or None)
            self.client = QdrantClient(host=h, port=p, api_key=k, check_compatibility=False)

    def collection_exists(self, collection_name: str) -> bool:
        """Check if a vector collection exists in Qdrant."""
        return bool(self.client.collection_exists(collection_name))

    def ensure_collection(
        self,
        collection_name: str,
        vector_size: int = 768,
        distance: Distance = Distance.COSINE,
    ) -> None:
        """Create collection if it does not exist already."""
        if not self.collection_exists(collection_name):
            logger.info(f"Creating Qdrant collection '{collection_name}' with size {vector_size}")
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=vector_size, distance=distance),
            )

    def upsert_points(
        self,
        collection_name: str,
        points: list[dict[str, Any]],
    ) -> None:
        """Upsert points into a given collection."""
        struct_points = [
            PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p.get("payload", {}),
            )
            for p in points
        ]
        self.client.upsert(
            collection_name=collection_name,
            points=struct_points,
        )

    def search(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int = 4,
        filter_key: str | None = None,
        filter_value: Any = None,
    ) -> list[dict[str, Any]]:
        """Perform cosine similarity vector search with optional payload filter."""
        query_filter = None
        if filter_key is not None and filter_value is not None:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key=filter_key,
                        match=MatchValue(value=filter_value),
                    )
                ]
            )

        response = self.client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=limit,
            query_filter=query_filter,
        )

        results: list[dict[str, Any]] = []
        for pt in response.points:
            results.append(
                {
                    "id": pt.id,
                    "score": pt.score,
                    "payload": pt.payload or {},
                }
            )
        return results

    def delete_collection(self, collection_name: str) -> None:
        """Delete an existing collection."""
        if self.collection_exists(collection_name):
            self.client.delete_collection(collection_name=collection_name)
