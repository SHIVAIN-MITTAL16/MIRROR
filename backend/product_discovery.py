"""Server-side adapter for the documented Channel3 product search API."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/api/products", tags=["Product discovery"])
CHANNEL3_BASE_URL = "https://api.trychannel3.com"


class ProductSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=300)
    limit: int = Field(default=10, ge=1, le=20)


def channel3_configured() -> bool:
    return bool(os.getenv("CHANNEL3_API_KEY", "").strip())


def _channel3_request(path: str, method: str, body: dict | None = None) -> dict:
    key = os.getenv("CHANNEL3_API_KEY", "").strip()
    if not key:
        raise HTTPException(status_code=503, detail={
            "message": "Channel3 product discovery is not configured.",
            "required_environment": ["CHANNEL3_API_KEY"],
        })
    request = Request(
        f"{CHANNEL3_BASE_URL}{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"x-api-key": key, "Accept": "application/json", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(request, timeout=20) as response:
            content = response.read(1_000_001)
        if len(content) > 1_000_000:
            raise HTTPException(status_code=502, detail="Channel3 response exceeded the size limit")
        value = json.loads(content.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("response must be an object")
        return value
    except HTTPError as error:
        # Keep provider response bodies private; do not log keys or buyer queries.
        raise HTTPException(status_code=502, detail=f"Channel3 request failed (HTTP {error.code}).") from error
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise HTTPException(status_code=502, detail="Channel3 product discovery is temporarily unavailable.") from error


def _product_row(product: dict) -> dict:
    offers = product.get("offers") if isinstance(product.get("offers"), list) else []
    attributes = product.get("structured_attributes")
    return {
        "product_id": product.get("id"),
        "title": product.get("title"),
        "brand": product.get("brand"),
        "model": product.get("model"),
        "description": product.get("description"),
        "product_url": product.get("url"),
        "image_url": product.get("image_url"),
        "structured_attributes": attributes if isinstance(attributes, dict) else {},
        "offers": offers,
        "source": "Channel3",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/config")
def product_discovery_config():
    return {"configured": channel3_configured(), "provider": "Channel3"}


@router.post("/search")
def search_products(payload: ProductSearchRequest):
    response = _channel3_request("/v1/search", "POST", {"query": payload.query, "limit": payload.limit})
    records = response.get("items", response.get("data", []))
    if not isinstance(records, list):
        raise HTTPException(status_code=502, detail="Channel3 returned an unsupported product response")
    return {
        "source": "Channel3",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "products": [_product_row(item) for item in records if isinstance(item, dict)],
    }


@router.get("/{product_id}")
def get_product(product_id: str):
    # Product IDs are encoded as a single path segment; arbitrary URLs are never fetched.
    from urllib.parse import quote
    if not product_id or len(product_id) > 160:
        raise HTTPException(status_code=422, detail="product_id must be between 1 and 160 characters")
    response = _channel3_request(f"/v1/products/{quote(product_id, safe='')}", "GET")
    product = response.get("product", response)
    if not isinstance(product, dict):
        raise HTTPException(status_code=502, detail="Channel3 returned an unsupported product response")
    return _product_row(product)
