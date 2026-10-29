"""Catalog metadata, distinct from verified provider coverage."""

from typing import Annotated

from fastapi import APIRouter, Query

from ..languages.catalog import search, upstream

router = APIRouter(prefix="/languages", tags=["languages"])


@router.get("")
def languages(
    q: Annotated[str, Query(max_length=100)] = "",
    include_auto: bool = False,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    items = search(q, include_auto)
    return {"items": items[offset : offset + limit], "total": len(items), "upstream": upstream()}
