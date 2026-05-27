"""
Announcement endpoints for the High School Management System API
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query

from ..database import announcements_collection, teachers_collection

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


def _parse_datetime(value: Optional[str], field_name: str, required: bool = False) -> Optional[datetime]:
    """Parse ISO-8601 datetime values sent from frontend forms."""
    if value is None or value.strip() == "":
        if required:
            raise HTTPException(status_code=400, detail=f"{field_name} is required")
        return None

    normalized = value.strip().replace("Z", "+00:00")

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a valid ISO datetime") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _serialize_announcement(document: Dict[str, Any]) -> Dict[str, Any]:
    """Convert MongoDB document to API response model."""
    starts_at = document.get("starts_at")
    expires_at = document.get("expires_at")
    created_at = document.get("created_at")
    updated_at = document.get("updated_at")

    return {
        "id": str(document.get("_id")),
        "message": document.get("message", ""),
        "starts_at": starts_at.isoformat() if isinstance(starts_at, datetime) else None,
        "expires_at": expires_at.isoformat() if isinstance(expires_at, datetime) else None,
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
        "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else None,
        "created_by": document.get("created_by", "")
    }


def _require_authenticated_teacher(teacher_username: Optional[str]) -> Dict[str, Any]:
    """Validate teacher identity for announcement management actions."""
    if not teacher_username:
        raise HTTPException(status_code=401, detail="Authentication required for this action")

    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")

    return teacher


@router.get("", response_model=List[Dict[str, Any]])
@router.get("/", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Return only active announcements (already started and not expired)."""
    now = datetime.now(timezone.utc)
    query = {
        "expires_at": {"$gt": now},
        "$or": [
            {"starts_at": None},
            {"starts_at": {"$exists": False}},
            {"starts_at": {"$lte": now}}
        ]
    }

    cursor = announcements_collection.find(query).sort([("expires_at", 1), ("created_at", -1)])
    return [_serialize_announcement(doc) for doc in cursor]


@router.get("/manage", response_model=List[Dict[str, Any]])
def list_announcements_for_management(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """List all announcements for authenticated users managing content."""
    _require_authenticated_teacher(teacher_username)

    cursor = announcements_collection.find({}).sort([("created_at", -1)])
    return [_serialize_announcement(doc) for doc in cursor]


@router.post("", response_model=Dict[str, Any])
def create_announcement(
    message: str,
    expires_at: str,
    starts_at: Optional[str] = None,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Create a new announcement. Expiration date is mandatory."""
    teacher = _require_authenticated_teacher(teacher_username)

    cleaned_message = message.strip()
    if not cleaned_message:
        raise HTTPException(status_code=400, detail="message is required")

    parsed_starts_at = _parse_datetime(starts_at, "starts_at")
    parsed_expires_at = _parse_datetime(expires_at, "expires_at", required=True)

    if parsed_starts_at and parsed_starts_at >= parsed_expires_at:
        raise HTTPException(status_code=400, detail="starts_at must be before expires_at")

    now = datetime.now(timezone.utc)
    document = {
        "message": cleaned_message,
        "starts_at": parsed_starts_at,
        "expires_at": parsed_expires_at,
        "created_at": now,
        "updated_at": now,
        "created_by": teacher["username"]
    }

    result = announcements_collection.insert_one(document)
    created_document = announcements_collection.find_one({"_id": result.inserted_id})

    if not created_document:
        raise HTTPException(status_code=500, detail="Failed to create announcement")

    return _serialize_announcement(created_document)


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    message: str,
    expires_at: str,
    starts_at: Optional[str] = None,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Update an existing announcement."""
    _require_authenticated_teacher(teacher_username)

    cleaned_message = message.strip()
    if not cleaned_message:
        raise HTTPException(status_code=400, detail="message is required")

    parsed_starts_at = _parse_datetime(starts_at, "starts_at")
    parsed_expires_at = _parse_datetime(expires_at, "expires_at", required=True)

    if parsed_starts_at and parsed_starts_at >= parsed_expires_at:
        raise HTTPException(status_code=400, detail="starts_at must be before expires_at")

    try:
        object_id = ObjectId(announcement_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid announcement id") from exc

    result = announcements_collection.update_one(
        {"_id": object_id},
        {
            "$set": {
                "message": cleaned_message,
                "starts_at": parsed_starts_at,
                "expires_at": parsed_expires_at,
                "updated_at": datetime.now(timezone.utc)
            }
        }
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    updated_document = announcements_collection.find_one({"_id": object_id})
    if not updated_document:
        raise HTTPException(status_code=500, detail="Failed to load updated announcement")

    return _serialize_announcement(updated_document)


@router.delete("/{announcement_id}", response_model=Dict[str, str])
def delete_announcement(
    announcement_id: str,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, str]:
    """Delete announcement by ID."""
    _require_authenticated_teacher(teacher_username)

    try:
        object_id = ObjectId(announcement_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid announcement id") from exc

    result = announcements_collection.delete_one({"_id": object_id})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted successfully"}
