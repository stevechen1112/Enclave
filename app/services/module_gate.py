"""Product module gating helpers."""
from __future__ import annotations

from fastapi import HTTPException, status

from app.services.product_license import ProductModule, is_module_enabled


def require_module(module: ProductModule) -> None:
    """Raise 403 if a commercial pack is disabled."""
    if not is_module_enabled(module):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "module_disabled",
                "module": module.value,
                "message": f"產品模組 {module.value} 未啟用",
            },
        )
