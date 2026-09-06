"""Product Pydantic schemas."""

from pydantic import BaseModel, ConfigDict, Field


class ProductCard(BaseModel):
    """Compact product card for carousel/catalog display."""

    sku: str
    name: str
    price: float
    discount_price: float | None = None
    image_url: str | None = None
    website_url: str | None = None
    product_url: str | None = None


class ProductDetail(BaseModel):
    """Full product detail schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    description: str | None = None
    category_name: str | None = None
    price: float
    discount_price: float | None = None
    images: list[str] = Field(default_factory=list)
    videos: list[str] = Field(default_factory=list)
    website_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    is_active: bool = True


class CatalogResponse(BaseModel):
    """Response for catalog/category browsing."""

    category: str
    total_count: int
    products: list[ProductCard] = Field(
        ..., min_length=1, max_length=4, description="3-4 products from the catalog"
    )


class ProductCreate(BaseModel):
    """Schema for creating a new product."""

    sku: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    category_id: int | None = None
    price: float = Field(..., gt=0)
    discount_price: float | None = Field(default=None, gt=0)
    images: list[str] = Field(default_factory=list)
    videos: list[str] = Field(default_factory=list)
    website_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    is_active: bool = True


class ProductUpdate(BaseModel):
    """Schema for updating a product."""

    name: str | None = None
    description: str | None = None
    category_id: int | None = None
    price: float | None = Field(default=None, gt=0)
    discount_price: float | None = Field(default=None, gt=0)
    images: list[str] | None = None
    videos: list[str] | None = None
    website_url: str | None = None
    tags: list[str] | None = None
    is_active: bool | None = None
