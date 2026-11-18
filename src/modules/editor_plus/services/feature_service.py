"""Service layer for CE features:
    - FeatureGroupService     -> feature_groups
    - MainFeatureService      -> main_features
    - TemplateFeatureService  -> template_features (ce_template <-> main_features mapping)

All methods take Pydantic input schemas and return Pydantic output schemas,
so ORM objects never leak out of this layer.
"""
from sqlalchemy import and_, case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.modules.editor_plus.models.feature_group_model import FeatureGroup
from src.modules.editor_plus.models.feature_model import MainFeature
from src.modules.editor_plus.models.template_feature_model import TemplateFeature
from src.modules.editor_plus.models.template_model import Template
from src.modules.editor_plus.schemas.api_envelope import PagedData
from src.modules.editor_plus.schemas.feature_group_schema import (
    FeatureGroupCreate,
    FeatureGroupDeleteData,
    FeatureGroupResponse,
    FeatureGroupUpdate,
)
from src.modules.editor_plus.schemas.feature_schema import (
    MainFeatureCreate,
    MainFeatureResponse,
    MainFeatureUpdate,
)
from src.modules.editor_plus.schemas.template_feature_schema import (
    GroupFeatureStatusData,
    GroupFeatureStatusItem,
    TemplateFeatureAdd,
    TemplateFeatureAddData,
    TemplateFeatureItem,
    TemplateFeatureListData,
    TemplateFeatureReplace,
    TemplateFeatureStatusOut,
    TemplateFeatureUpsert,
    TemplateFeatureUpsertData,
)


# ==================== Errors (router maps status_code -> HTTP) ====================
class FeatureServiceError(Exception):
    status_code = 400


class NotFoundError(FeatureServiceError):
    status_code = 404


class ConflictError(FeatureServiceError):
    status_code = 409


class InvalidReferenceError(FeatureServiceError):
    status_code = 400


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _require_name(value: str | None, label: str) -> str:
    value = _clean(value)
    if not value:
        raise FeatureServiceError(f"{label} cannot be empty")
    return value


# ==================== Feature Groups ====================
class FeatureGroupService:

    def _get(self, db: Session, feature_group_id: int) -> FeatureGroup:
        group = db.query(FeatureGroup).filter(FeatureGroup.feature_group_id == feature_group_id).first()
        if not group:
            raise NotFoundError("Feature group not found")
        return group

    GROUP_CODE_STEP = 1000

    def _next_group_code(self, db: Session) -> int:
        """0 for the first group, then the next multiple of 1000 above the current max
        (0, 1000, 2000, ... 11000, 12000). Codes freed by deletes are not reused."""
        max_code = db.query(func.max(FeatureGroup.group_code)).scalar()
        if max_code is None:
            return 0
        return (max_code // self.GROUP_CODE_STEP + 1) * self.GROUP_CODE_STEP

    def create(self, db: Session, payload: FeatureGroupCreate) -> FeatureGroupResponse:
        group_name = _require_name(payload.group_name, "group_name")
        group_description = _clean(payload.group_description)

        # Two concurrent creates can compute the same code; the UNIQUE index rejects one, so retry.
        for _ in range(3):
            group = FeatureGroup(
                group_name=group_name,
                group_code=self._next_group_code(db),
                group_description=group_description,
                created_by=payload.created_by,
            )
            db.add(group)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                continue
            db.refresh(group)
            return FeatureGroupResponse.model_validate(group)
        raise ConflictError("Could not allocate a unique group_code, please retry")

    def list(
        self, db: Session, search: str | None = None, skip: int = 0, limit: int = 100
    ) -> PagedData[FeatureGroupResponse]:
        query = db.query(FeatureGroup)
        search = _clean(search)
        if search:
            query = query.filter(FeatureGroup.group_name.ilike(f"%{search}%"))
        total = query.count()
        rows = query.order_by(FeatureGroup.group_code.asc()).offset(skip).limit(limit).all()
        return PagedData[FeatureGroupResponse](
            total=total, skip=skip, limit=limit,
            items=[FeatureGroupResponse.model_validate(r) for r in rows],
        )

    def get(self, db: Session, feature_group_id: int) -> FeatureGroupResponse:
        return FeatureGroupResponse.model_validate(self._get(db, feature_group_id))

    def update(self, db: Session, feature_group_id: int, payload: FeatureGroupUpdate) -> FeatureGroupResponse:
        group = self._get(db, feature_group_id)
        data = payload.model_dump(exclude_unset=True)

        if "group_name" in data:
            group.group_name = _require_name(data["group_name"], "group_name")

        # group_code is system-generated and immutable (main_features references it)

        if "group_description" in data:
            group.group_description = _clean(data["group_description"])

        if "updated_by" in data:
            group.updated_by = data["updated_by"]

        db.commit()
        db.refresh(group)
        return FeatureGroupResponse.model_validate(group)

    def delete(self, db: Session, feature_group_id: int) -> FeatureGroupDeleteData:
        """Deletes the group. Its features (and their template mappings) are removed
        by the DB's ON DELETE CASCADE."""
        group = self._get(db, feature_group_id)
        feature_count = db.query(MainFeature).filter(MainFeature.group_code == group.group_code).count()
        db.delete(group)
        db.commit()
        db.expire_all()
        return FeatureGroupDeleteData(feature_group_id=feature_group_id, deleted_feature_count=feature_count)


# ==================== Main Features ====================
class MainFeatureService:

    def _get(self, db: Session, feature_id: int) -> MainFeature:
        feature = db.query(MainFeature).filter(MainFeature.feature_id == feature_id).first()
        if not feature:
            raise NotFoundError("Feature not found")
        return feature

    def _ensure_code_unique(self, db: Session, feature_code: int, exclude_id: int | None = None) -> None:
        query = db.query(MainFeature.feature_id).filter(MainFeature.feature_code == feature_code)
        if exclude_id is not None:
            query = query.filter(MainFeature.feature_id != exclude_id)
        if query.first():
            raise ConflictError(f"Feature with feature_code {feature_code} already exists")

    def _ensure_group_exists(self, db: Session, group_code: int | None) -> None:
        if group_code is None:
            return
        if not db.query(FeatureGroup.feature_group_id).filter(FeatureGroup.group_code == group_code).first():
            raise InvalidReferenceError(f"Feature group with group_code {group_code} does not exist")

    def create(self, db: Session, payload: MainFeatureCreate) -> MainFeatureResponse:
        self._ensure_code_unique(db, payload.feature_code)
        self._ensure_group_exists(db, payload.group_code)
        feature = MainFeature(
            feature_name=_require_name(payload.feature_name, "feature_name"),
            feature_code=payload.feature_code,
            group_code=payload.group_code,
            feature_description=_clean(payload.feature_description),
            created_by=payload.created_by,
        )
        db.add(feature)
        db.commit()
        db.refresh(feature)
        return MainFeatureResponse.model_validate(feature)

    def list(
        self,
        db: Session,
        group_code: int | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> PagedData[MainFeatureResponse]:
        query = db.query(MainFeature)
        if group_code is not None:
            query = query.filter(MainFeature.group_code == group_code)
        search = _clean(search)
        if search:
            query = query.filter(MainFeature.feature_name.ilike(f"%{search}%"))
        total = query.count()
        rows = query.order_by(MainFeature.feature_code.asc()).offset(skip).limit(limit).all()
        return PagedData[MainFeatureResponse](
            total=total, skip=skip, limit=limit,
            items=[MainFeatureResponse.model_validate(r) for r in rows],
        )

    def get(self, db: Session, feature_id: int) -> MainFeatureResponse:
        return MainFeatureResponse.model_validate(self._get(db, feature_id))

    def update(self, db: Session, feature_id: int, payload: MainFeatureUpdate) -> MainFeatureResponse:
        feature = self._get(db, feature_id)
        data = payload.model_dump(exclude_unset=True)

        if "feature_name" in data:
            feature.feature_name = _require_name(data["feature_name"], "feature_name")

        if "feature_code" in data:
            if data["feature_code"] is None:
                raise FeatureServiceError("feature_code cannot be null")
            self._ensure_code_unique(db, data["feature_code"], exclude_id=feature_id)
            feature.feature_code = data["feature_code"]

        if "group_code" in data:  # null allowed: detaches from group
            self._ensure_group_exists(db, data["group_code"])
            feature.group_code = data["group_code"]

        if "feature_description" in data:
            feature.feature_description = _clean(data["feature_description"])

        if "updated_by" in data:
            feature.updated_by = data["updated_by"]

        db.commit()
        db.expire(feature, ["group"])  # reload group if group_code changed
        db.refresh(feature)
        return MainFeatureResponse.model_validate(feature)

    def delete(self, db: Session, feature_id: int) -> None:
        """Deletes the feature. Its template mappings are removed by ON DELETE CASCADE."""
        feature = self._get(db, feature_id)
        db.delete(feature)
        db.commit()


# ==================== Template <-> Feature mapping ====================
class TemplateFeatureService:

    def _get_template(self, db: Session, template_id: int) -> Template:
        template = db.query(Template).filter(Template.template_id == template_id).first()
        if not template:
            raise NotFoundError("Template not found")
        return template

    def _validate_feature_ids(self, db: Session, feature_ids: list[int]) -> list[int]:
        """De-duplicates (keeping order) and checks every id exists."""
        unique_ids = list(dict.fromkeys(feature_ids))
        if not unique_ids:
            return []
        found = {
            fid for (fid,) in db.query(MainFeature.feature_id).filter(MainFeature.feature_id.in_(unique_ids)).all()
        }
        missing = [fid for fid in unique_ids if fid not in found]
        if missing:
            raise InvalidReferenceError(f"Feature id(s) not found: {missing}")
        return unique_ids

    def _mapped_ids(self, db: Session, template_id: int) -> set[int]:
        return {
            fid for (fid,) in db.query(TemplateFeature.feature_id).filter(TemplateFeature.template_id == template_id).all()
        }

    def list(self, db: Session, template_id: int) -> TemplateFeatureListData:
        template = self._get_template(db, template_id)
        rows = (
            db.query(MainFeature)
            .join(TemplateFeature, TemplateFeature.feature_id == MainFeature.feature_id)
            .filter(TemplateFeature.template_id == template_id)
            .order_by(MainFeature.group_code.asc(), MainFeature.feature_code.asc())
            .all()
        )
        return TemplateFeatureListData(
            template_id=template.template_id,
            template_name=template.template_name,
            total=len(rows),
            features=[TemplateFeatureItem.model_validate(r) for r in rows],
        )

    def list_by_group(
        self, db: Session, group_code: int, template_id: int | None = None
    ) -> GroupFeatureStatusData:
        """Features of a group with an on/off status for the template.

        - template_id missing, or template has no rows in template_features -> every feature status=1
        - otherwise -> stored template_features.status if mapped, else 0
        """
        group = db.query(FeatureGroup).filter(FeatureGroup.group_code == group_code).first()
        if not group:
            raise NotFoundError(f"Feature group with group_code {group_code} not found")

        template_mapped = bool(
            template_id is not None
            and db.query(TemplateFeature.id).filter(TemplateFeature.template_id == template_id).first()
        )

        if template_mapped:
            status_col = case((TemplateFeature.id.isnot(None), TemplateFeature.status), else_=0)
            query = db.query(
                MainFeature.feature_id, MainFeature.feature_name, MainFeature.feature_code, status_col.label("status")
            ).outerjoin(
                TemplateFeature,
                and_(TemplateFeature.feature_id == MainFeature.feature_id, TemplateFeature.template_id == template_id),
            )
        else:
            query = db.query(MainFeature.feature_id, MainFeature.feature_name, MainFeature.feature_code)

        rows = query.filter(MainFeature.group_code == group.group_code).order_by(MainFeature.feature_code.asc()).all()
        features = [
            GroupFeatureStatusItem(
                feature_id=r.feature_id,
                feature_name=r.feature_name,
                feature_code=r.feature_code,
                status=r.status if template_mapped else 1,
            )
            for r in rows
        ]
        return GroupFeatureStatusData(
            feature_group_id=group.feature_group_id,
            group_code=group.group_code,
            group_name=group.group_name,
            template_id=template_id,
            template_mapped=template_mapped,
            total=len(features),
            features=features,
        )

    def upsert(self, db: Session, payload: TemplateFeatureUpsert) -> TemplateFeatureUpsertData:
        """Bulk upsert for one template, in a single transaction:
        insert missing (template_id, feature_id, status) rows, update status on existing ones."""
        template_id = payload.template_id
        self._get_template(db, template_id)
        wanted = {item.feature_id: item.status for item in payload.features}
        self._validate_feature_ids(db, list(wanted))

        for attempt in range(2):  # retry once if a concurrent request inserted the same pair
            existing = {
                row.feature_id: row
                for row in db.query(TemplateFeature).filter(
                    TemplateFeature.template_id == template_id,
                    TemplateFeature.feature_id.in_(list(wanted)),
                )
            }
            inserted, updated = [], []
            for feature_id, status in wanted.items():
                row = existing.get(feature_id)
                if row is None:
                    db.add(TemplateFeature(template_id=template_id, feature_id=feature_id, status=status))
                    inserted.append(feature_id)
                else:
                    row.status = status
                    updated.append(feature_id)
            try:
                db.commit()
                break
            except IntegrityError:
                db.rollback()
                if attempt:
                    raise ConflictError("Concurrent update on this template's features, please retry")

        return TemplateFeatureUpsertData(
            template_id=template_id,
            inserted=inserted,
            updated=updated,
            features=[TemplateFeatureStatusOut(feature_id=fid, status=st) for fid, st in wanted.items()],
        )

    def add(self, db: Session, template_id: int, payload: TemplateFeatureAdd) -> TemplateFeatureAddData:
        self._get_template(db, template_id)
        feature_ids = self._validate_feature_ids(db, payload.feature_ids)
        existing = self._mapped_ids(db, template_id)

        added = [fid for fid in feature_ids if fid not in existing]
        db.add_all([TemplateFeature(template_id=template_id, feature_id=fid) for fid in added])
        db.commit()
        return TemplateFeatureAddData(
            template_id=template_id,
            added=added,
            already_mapped=[fid for fid in feature_ids if fid in existing],
        )

    def replace(self, db: Session, template_id: int, payload: TemplateFeatureReplace) -> TemplateFeatureListData:
        self._get_template(db, template_id)
        wanted = set(self._validate_feature_ids(db, payload.feature_ids))
        existing = self._mapped_ids(db, template_id)

        to_remove = existing - wanted
        if to_remove:
            db.query(TemplateFeature).filter(
                TemplateFeature.template_id == template_id,
                TemplateFeature.feature_id.in_(to_remove),
            ).delete(synchronize_session=False)
        db.add_all([TemplateFeature(template_id=template_id, feature_id=fid) for fid in wanted - existing])
        db.commit()
        return self.list(db, template_id)

    def remove(self, db: Session, template_id: int, feature_id: int) -> None:
        self._get_template(db, template_id)
        deleted = (
            db.query(TemplateFeature)
            .filter(TemplateFeature.template_id == template_id, TemplateFeature.feature_id == feature_id)
            .delete(synchronize_session=False)
        )
        if not deleted:
            raise NotFoundError("Feature is not mapped to this template")
        db.commit()
