"""CE Features endpoints: feature groups, main features, and template-feature mapping.

Mount in api_router.py:
    api_router.include_router(ce_features_router, prefix="/editor", tags=["CE Features"])
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.modules.editor_plus.schemas.feature_group_schema import (
    FeatureGroupCreate,
    FeatureGroupDeleteAPIResponse,
    FeatureGroupListAPIResponse,
    FeatureGroupSingleAPIResponse,
    FeatureGroupUpdate,
)
from src.modules.editor_plus.schemas.feature_schema import (
    MainFeatureCreate,
    MainFeatureDeleteAPIResponse,
    MainFeatureDeleteData,
    MainFeatureListAPIResponse,
    MainFeatureSingleAPIResponse,
    MainFeatureUpdate,
)
from src.modules.editor_plus.schemas.template_feature_schema import (
    GroupFeatureStatusAPIResponse,
    TemplateFeatureAdd,
    TemplateFeatureAddAPIResponse,
    TemplateFeatureListAPIResponse,
    TemplateFeatureRemoveAPIResponse,
    TemplateFeatureRemoveData,
    TemplateFeatureReplace,
    TemplateFeatureUpsert,
    TemplateFeatureUpsertAPIResponse,
)
from src.modules.editor_plus.services.feature_service import (
    FeatureGroupService,
    FeatureServiceError,
    MainFeatureService,
    TemplateFeatureService,
)

router = APIRouter()
group_service = FeatureGroupService()
feature_service = MainFeatureService()
template_feature_service = TemplateFeatureService()


def _http(e: FeatureServiceError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


def _parse_optional_id(value: Optional[str], name: str) -> Optional[int]:
    """Treat missing, '', 'null', 'undefined', 'none' and 0 as no id (frontends often send these)."""
    if value is None or value.strip().lower() in ("", "null", "undefined", "none", "0"):
        return None
    try:
        parsed = int(value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{name} must be an integer or null")
    if parsed < 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{name} must be positive")
    return parsed


# ==================== Feature Groups ====================
@router.post("/feature-groups", status_code=status.HTTP_201_CREATED, response_model=FeatureGroupSingleAPIResponse)
def create_feature_group(payload: FeatureGroupCreate, db: Session = Depends(get_db)):
    """Create a feature group. group_code is auto-generated (0, 1000, 2000, ...)."""
    try:
        data = group_service.create(db, payload)
    except FeatureServiceError as e:
        raise _http(e)
    return FeatureGroupSingleAPIResponse(
        response_code=status.HTTP_201_CREATED, message="Feature group created successfully", data=data
    )


@router.get("/feature-groups", response_model=FeatureGroupListAPIResponse)
def list_feature_groups(
    search: Optional[str] = Query(None, description="Filter by group name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List feature groups (ordered by group_code)."""
    data = group_service.list(db, search=search, skip=skip, limit=limit)
    return FeatureGroupListAPIResponse(
        response_code=status.HTTP_200_OK, message="Feature groups retrieved successfully", data=data
    )


@router.get("/feature-groups/{feature_group_id}", response_model=FeatureGroupSingleAPIResponse)
def get_feature_group(feature_group_id: int, db: Session = Depends(get_db)):
    """Get a feature group by ID."""
    try:
        data = group_service.get(db, feature_group_id)
    except FeatureServiceError as e:
        raise _http(e)
    return FeatureGroupSingleAPIResponse(
        response_code=status.HTTP_200_OK, message="Feature group retrieved successfully", data=data
    )


@router.put("/feature-groups/{feature_group_id}", response_model=FeatureGroupSingleAPIResponse)
def update_feature_group(feature_group_id: int, payload: FeatureGroupUpdate, db: Session = Depends(get_db)):
    """Update a feature group. Only fields sent in the body are changed."""
    try:
        data = group_service.update(db, feature_group_id, payload)
    except FeatureServiceError as e:
        raise _http(e)
    return FeatureGroupSingleAPIResponse(
        response_code=status.HTTP_200_OK, message="Feature group updated successfully", data=data
    )


@router.delete("/feature-groups/{feature_group_id}", response_model=FeatureGroupDeleteAPIResponse)
def delete_feature_group(feature_group_id: int, db: Session = Depends(get_db)):
    """Delete a feature group. WARNING: also deletes its features and their template mappings (DB cascade)."""
    try:
        data = group_service.delete(db, feature_group_id)
    except FeatureServiceError as e:
        raise _http(e)
    return FeatureGroupDeleteAPIResponse(
        response_code=status.HTTP_200_OK, message="Feature group deleted successfully", data=data
    )


# ==================== Main Features ====================
@router.post("/features", status_code=status.HTTP_201_CREATED, response_model=MainFeatureSingleAPIResponse)
def create_feature(payload: MainFeatureCreate, db: Session = Depends(get_db)):
    """Create a feature."""
    try:
        data = feature_service.create(db, payload)
    except FeatureServiceError as e:
        raise _http(e)
    return MainFeatureSingleAPIResponse(
        response_code=status.HTTP_201_CREATED, message="Feature created successfully", data=data
    )


@router.get("/features", response_model=MainFeatureListAPIResponse)
def list_features(
    group_code: Optional[int] = Query(None, ge=0, description="Filter by group"),
    search: Optional[str] = Query(None, description="Filter by feature name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List features (ordered by feature_code)."""
    data = feature_service.list(db, group_code=group_code, search=search, skip=skip, limit=limit)
    return MainFeatureListAPIResponse(
        response_code=status.HTTP_200_OK, message="Features retrieved successfully", data=data
    )


@router.get("/features/{feature_id}", response_model=MainFeatureSingleAPIResponse)
def get_feature(feature_id: int, db: Session = Depends(get_db)):
    """Get a feature by ID."""
    try:
        data = feature_service.get(db, feature_id)
    except FeatureServiceError as e:
        raise _http(e)
    return MainFeatureSingleAPIResponse(
        response_code=status.HTTP_200_OK, message="Feature retrieved successfully", data=data
    )


@router.put("/features/{feature_id}", response_model=MainFeatureSingleAPIResponse)
def update_feature(feature_id: int, payload: MainFeatureUpdate, db: Session = Depends(get_db)):
    """Update a feature. Only fields sent in the body are changed."""
    try:
        data = feature_service.update(db, feature_id, payload)
    except FeatureServiceError as e:
        raise _http(e)
    return MainFeatureSingleAPIResponse(
        response_code=status.HTTP_200_OK, message="Feature updated successfully", data=data
    )


@router.delete("/features/{feature_id}", response_model=MainFeatureDeleteAPIResponse)
def delete_feature(feature_id: int, db: Session = Depends(get_db)):
    """Delete a feature. Its template mappings are removed too (DB cascade)."""
    try:
        feature_service.delete(db, feature_id)
    except FeatureServiceError as e:
        raise _http(e)
    return MainFeatureDeleteAPIResponse(
        response_code=status.HTTP_200_OK,
        message="Feature deleted successfully",
        data=MainFeatureDeleteData(feature_id=feature_id),
    )


# ==================== Template <-> Feature mapping ====================
@router.put("/template-features", response_model=TemplateFeatureUpsertAPIResponse)
def upsert_template_feature(payload: TemplateFeatureUpsert, db: Session = Depends(get_db)):
    """Bulk upsert template_features for one template: inserts new (feature_id, status) pairs,
    updates status on existing ones. All-or-nothing (single transaction)."""
    try:
        data = template_feature_service.upsert(db, payload)
    except FeatureServiceError as e:
        raise _http(e)
    return TemplateFeatureUpsertAPIResponse(
        response_code=status.HTTP_200_OK,
        message=f"Template features saved: {len(data.inserted)} inserted, {len(data.updated)} updated",
        data=data,
    )


@router.get("/feature-groups-features/{group_code}", response_model=GroupFeatureStatusAPIResponse)
def list_group_features_for_template(
    group_code: int,
    template_id: Optional[str] = Query(
        None, description="Template to resolve feature status against. Omit / empty / null -> all features status 1"
    ),
    db: Session = Depends(get_db),
):
    """List a group's features with status (1/0) for a template.
    If the template has no mappings in template_features (or no template_id), every feature is status 1."""
    tid = _parse_optional_id(template_id, "template_id")
    try:
        data = template_feature_service.list_by_group(db, group_code, tid)
    except FeatureServiceError as e:
        raise _http(e)
    return GroupFeatureStatusAPIResponse(
        response_code=status.HTTP_200_OK, message="Group features retrieved successfully", data=data
    )


@router.get("/templates/{template_id}/features", response_model=TemplateFeatureListAPIResponse)
def list_template_features(template_id: int, db: Session = Depends(get_db)):
    """List features mapped to a template."""
    try:
        data = template_feature_service.list(db, template_id)
    except FeatureServiceError as e:
        raise _http(e)
    return TemplateFeatureListAPIResponse(
        response_code=status.HTTP_200_OK, message="Template features retrieved successfully", data=data
    )


@router.post(
    "/templates/{template_id}/features",
    status_code=status.HTTP_201_CREATED,
    response_model=TemplateFeatureAddAPIResponse,
)
def add_template_features(template_id: int, payload: TemplateFeatureAdd, db: Session = Depends(get_db)):
    """Map features to a template. Already-mapped ids are skipped."""
    try:
        data = template_feature_service.add(db, template_id, payload)
    except FeatureServiceError as e:
        raise _http(e)
    return TemplateFeatureAddAPIResponse(
        response_code=status.HTTP_201_CREATED, message="Features mapped to template successfully", data=data
    )


@router.put("/templates/{template_id}/features", response_model=TemplateFeatureListAPIResponse)
def replace_template_features(template_id: int, payload: TemplateFeatureReplace, db: Session = Depends(get_db)):
    """Replace the template's full feature set (empty list clears all)."""
    try:
        data = template_feature_service.replace(db, template_id, payload)
    except FeatureServiceError as e:
        raise _http(e)
    return TemplateFeatureListAPIResponse(
        response_code=status.HTTP_200_OK, message="Template features updated successfully", data=data
    )


@router.delete("/templates/{template_id}/features/{feature_id}", response_model=TemplateFeatureRemoveAPIResponse)
def remove_template_feature(template_id: int, feature_id: int, db: Session = Depends(get_db)):
    """Unmap one feature from a template."""
    try:
        template_feature_service.remove(db, template_id, feature_id)
    except FeatureServiceError as e:
        raise _http(e)
    return TemplateFeatureRemoveAPIResponse(
        response_code=status.HTTP_200_OK,
        message="Feature removed from template successfully",
        data=TemplateFeatureRemoveData(template_id=template_id, feature_id=feature_id),
    )
