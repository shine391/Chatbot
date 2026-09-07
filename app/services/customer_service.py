"""Customer service module for customer lifecycle and tagging."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer, Platform
from app.schemas.customer import CustomerCreate, CustomerUpdate


class CustomerService:
    """Manages customer profiles, persistence, and tagging."""

    def __init__(self, session: AsyncSession, tenant_id: str = "default-system-tenant") -> None:
        self.session = session
        self.tenant_id = tenant_id

    async def get_by_platform_id(
        self, platform: str | Platform, platform_user_id: str
    ) -> Customer | None:
        """Find customer by platform and user ID."""
        plat_val = platform.value if isinstance(platform, Platform) else platform
        stmt = select(Customer).where(
            Customer.platform == plat_val,
            Customer.platform_user_id == platform_user_id,
            Customer.tenant_id == self.tenant_id,
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_customer(self, data: CustomerCreate) -> Customer:
        """Create a new customer profile."""
        customer = Customer(
            tenant_id=self.tenant_id,
            platform=data.platform,
            platform_user_id=data.platform_user_id,
            name=data.name,
            email=data.email,
            phone=data.phone,
            tags=data.tags,
        )
        self.session.add(customer)
        await self.session.flush()
        return customer

    async def get_or_create(
        self,
        platform: str | Platform,
        platform_user_id: str,
        name: str | None = None,
    ) -> Customer:
        """Retrieve existing customer or instantiate a new profile."""
        existing = await self.get_by_platform_id(platform, platform_user_id)
        if existing:
            if name and not existing.name:
                existing.name = name
                await self.session.flush()
            setattr(existing, "_is_new", False)
            return existing

        plat_val = platform.value if isinstance(platform, Platform) else platform
        new_customer = Customer(
            tenant_id=self.tenant_id,
            platform=plat_val,
            platform_user_id=platform_user_id,
            name=name,
            tags={"status": "new"},
        )
        self.session.add(new_customer)
        await self.session.flush()
        setattr(new_customer, "_is_new", True)
        return new_customer

    async def update_customer(self, customer_id: int, data: CustomerUpdate) -> Customer | None:
        """Update existing customer details."""
        stmt = select(Customer).where(
            Customer.id == customer_id,
            Customer.tenant_id == self.tenant_id,
        )
        res = await self.session.execute(stmt)
        customer = res.scalar_one_or_none()
        if not customer:
            return None

        if data.name is not None:
            customer.name = data.name
        if data.email is not None:
            customer.email = data.email
        if data.phone is not None:
            customer.phone = data.phone
        if data.funnel_stage is not None:
            customer.funnel_stage = data.funnel_stage
        if data.notes is not None:
            customer.notes = data.notes
        if data.address is not None:
            customer.address = data.address
        if data.tags is not None:
            current_tags = customer.tags or {}
            current_tags.update(data.tags)
            customer.tags = current_tags

        await self.session.flush()
        return customer
