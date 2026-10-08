"""API v2 — placeholder for the next API generation.

Not implemented yet. This module exists purely to prove out the
versioning architecture end-to-end (an `/api/v2` prefix really is
mounted and responds) and to document how a real v2 should be built
once it's needed.

How to add v2 endpoints when the time comes:

    from fastapi import APIRouter
    from app.api.v1 import _v1_module_routers  # reuse unchanged v1 routers
    from app.modules.subscriptions.router_v2 import router as subscriptions_router_v2

    v2_router = APIRouter()
    for router in _v1_module_routers:
        if router is subscriptions_router:  # example: only subscriptions changed in v2
            continue
        v2_router.include_router(router)
    v2_router.include_router(subscriptions_router_v2)

i.e.: start from the full v1 route set, swap out only the routers whose
contract actually changed, and leave everything else byte-for-byte
identical — that's what keeps v1 clients working unmodified while v2
clients get the new behaviour, satisfying backward compatibility.
"""

from fastapi import APIRouter

v2_router = APIRouter()


@v2_router.get("/", tags=["System"], include_in_schema=False)
async def v2_not_yet_available():
    return {
        "success": True,
        "message": "API v2 is not implemented yet. Please use /api/v1.",
        "current_stable": "v1",
    }


__all__ = ["v2_router"]
