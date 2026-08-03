from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from security import SecurityMiddleware, SecurityPolicy
from sanitizer import ItemInputSanitizer, SanitizerError
from service import ItemIdParser, OwnerIntersectionService, SOURCE_CHOICES

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
POLICY = SecurityPolicy()
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://127.0.0.1:8787,http://localhost:8787",
    ).split(",")
    if origin.strip()
]

app = FastAPI(title="Rolimons Owner Finder", version="1.1.0")
service = OwnerIntersectionService()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.add_middleware(SecurityMiddleware, policy=POLICY)


class IntersectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[str] = Field(min_length=2, max_length=POLICY.max_items_per_search)

    @field_validator("items")
    @classmethod
    def validate_items(cls, values: list[str]) -> list[str]:
        try:
            return ItemInputSanitizer.sanitize_many(values)
        except SanitizerError as exc:
            raise ValueError(str(exc)) from exc


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "limits": {"hourly": POLICY.hourly_limit}}


@app.get("/api/sources")
def sources() -> dict:
    return {"sources": list(SOURCE_CHOICES)}


@app.post("/api/intersect")
def intersect(body: IntersectRequest, request: Request) -> dict:
    try:
        item_ids = ItemIdParser.parse_many(body.items)
        if len(item_ids) > POLICY.max_items_per_search:
            raise ValueError(f"max {POLICY.max_items_per_search} items per search")
        result = service.intersect(item_ids, source="auto")
        return result.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid request") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="internal error") from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/assets", StaticFiles(directory=WEB), name="assets")
