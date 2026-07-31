from app.modules.admin.router import router as admin_router
from app.modules.billing.admin_router import router as admin_billing_router

# Merge billing admin routes into the main admin router
admin_router.include_router(admin_billing_router)

__all__ = ["admin_router"]
