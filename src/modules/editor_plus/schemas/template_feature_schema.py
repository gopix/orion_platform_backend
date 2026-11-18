from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from src.modules.editor_plus.schemas.api_envelope import APIEnvelope


# ==================== Input ====================
class TemplateFeatureAdd(BaseModel):
    """Add features to a template (existing mappings are kept)."""

    feature_ids: List[int] = Field(..., min_length=1, examples=[[1, 2, 3]])


class TemplateFeatureReplace(BaseModel):
    """Replace the template's full feature set. Empty list clears all."""

    feature_ids: List[int] = Field(..., examples=[[1, 2, 3]])


class TemplateFeatureStatusIn(BaseModel):
    feature_id: int = Field(..., ge=1, examples=[1])
    status: Literal[0, 1] = Field(1, examples=[1])


class TemplateFeatureUpsert(BaseModel):
    """For each item: insert (template_id, feature_id, status), or update status if the pair exists."""

    template_id: int = Field(..., ge=1, examples=[5])
    features: List[TemplateFeatureStatusIn] = Field(
        ...,
        min_length=1,
        examples=[[{"feature_id": 1, "status": 1}, {"feature_id": 2, "status": 0}, {"feature_id": 3, "status": 1}]],
    )

    @field_validator("features")
    @classmethod
    def _no_duplicate_features(cls, v: List[TemplateFeatureStatusIn]) -> List[TemplateFeatureStatusIn]:
        seen, dupes = set(), set()
        for item in v:
            (dupes if item.feature_id in seen else seen).add(item.feature_id)
        if dupes:
            raise ValueError(f"duplicate feature_id(s) in features: {sorted(dupes)}")
        return v


# ==================== Output ====================
class TemplateFeatureItem(BaseModel):
    feature_id: int
    feature_name: str
    feature_code: int
    group_code: Optional[int] = None
    group_name: Optional[str] = None

    model_config = {"from_attributes": True}


class TemplateFeatureListData(BaseModel):
    template_id: int
    template_name: str
    total: int
    features: List[TemplateFeatureItem]


class TemplateFeatureAddData(BaseModel):
    template_id: int
    added: List[int]
    already_mapped: List[int]


class TemplateFeatureStatusOut(BaseModel):
    feature_id: int
    status: int


class TemplateFeatureUpsertData(BaseModel):
    template_id: int
    inserted: List[int]
    updated: List[int]
    features: List[TemplateFeatureStatusOut]


class TemplateFeatureRemoveData(BaseModel):
    template_id: int
    feature_id: int


class GroupFeatureStatusItem(BaseModel):
    feature_id: int
    feature_name: str
    feature_code: int
    status: int  # 1 = enabled, 0 = disabled


class GroupFeatureStatusData(BaseModel):
    feature_group_id: int
    group_code: int
    group_name: str
    template_id: Optional[int] = None
    template_mapped: bool  # False -> template has no mappings yet, all features default to status 1
    total: int
    features: List[GroupFeatureStatusItem]


TemplateFeatureListAPIResponse = APIEnvelope[TemplateFeatureListData]
GroupFeatureStatusAPIResponse = APIEnvelope[GroupFeatureStatusData]
TemplateFeatureAddAPIResponse = APIEnvelope[TemplateFeatureAddData]
TemplateFeatureRemoveAPIResponse = APIEnvelope[TemplateFeatureRemoveData]
TemplateFeatureUpsertAPIResponse = APIEnvelope[TemplateFeatureUpsertData]
