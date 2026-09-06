"""Product Catalog Service implementing BaseProductCatalog interface."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.interfaces import BaseProductCatalog
from app.models.product import Category, Product
from app.schemas.product import CatalogResponse, ProductCard, ProductDetail


class ProductCatalogService(BaseProductCatalog):
    """Database-backed service for searching products and generating 3-4 item catalog responses."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _to_detail(self, product: Product) -> ProductDetail:
        category_name = product.category.name if product.category else None
        return ProductDetail(
            id=product.id,
            sku=product.sku,
            name=product.name,
            description=product.description,
            category_name=category_name,
            price=product.price,
            discount_price=product.discount_price,
            images=product.images or [],
            videos=product.videos or [],
            website_url=product.website_url,
            tags=product.tags or [],
            is_active=product.is_active,
        )

    async def get_by_sku(self, sku: str) -> ProductDetail | None:
        """Retrieve active product by exact SKU."""
        clean_sku = sku.strip().upper()
        stmt = (
            select(Product)
            .options(selectinload(Product.category))
            .where(Product.sku == clean_sku, Product.is_active.is_(True))
        )
        result = await self.session.execute(stmt)
        product = result.scalar_one_or_none()
        if not product:
            return None
        return self._to_detail(product)

    async def search_products(self, query: str, limit: int = 4) -> list[ProductDetail]:
        """Search products by name, description, SKU, or tags."""
        term = f"%{query.strip()}%"
        stmt = (
            select(Product)
            .options(selectinload(Product.category))
            .where(
                Product.is_active.is_(True),
                or_(
                    Product.name.ilike(term),
                    Product.description.ilike(term),
                    Product.sku.ilike(term),
                ),
            )
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        products = result.scalars().all()
        return [self._to_detail(p) for p in products]

    async def get_catalog_by_category(self, category_slug: str, limit: int = 4) -> CatalogResponse:
        """Retrieve 3-4 products for category browsing."""
        # Enforce 3 to 4 items limit
        clamped_limit = max(1, min(4, limit))

        # Find category
        cat_stmt = select(Category).where(Category.slug == category_slug)
        cat_res = await self.session.execute(cat_stmt)
        category = cat_res.scalar_one_or_none()

        cat_id = category.id if category else None
        cat_title = category.name if category else category_slug

        # Fetch products
        prod_stmt = select(Product).where(Product.is_active.is_(True))
        if cat_id is not None:
            prod_stmt = prod_stmt.where(Product.category_id == cat_id)

        prod_res = await self.session.execute(prod_stmt)
        all_products = prod_res.scalars().all()

        total_count = len(all_products)
        selected_prods = all_products[:clamped_limit]

        cards = [
            ProductCard(
                sku=p.sku,
                name=p.name,
                price=p.price,
                discount_price=p.discount_price,
                image_url=p.images[0] if p.images else None,
                website_url=p.website_url,
                product_url=p.website_url,
            )
            for p in selected_prods
        ]

        return CatalogResponse(
            category=cat_title,
            total_count=total_count,
            products=cards,
        )
