from io import BytesIO
from typing import Any

from sqlalchemy import text

from src.core.database import SessionLocal
from src.modules.accessibility_plus.models.master_accessibility_model import MasterAccessibilityModel
from src.modules.accessibility_plus.models.org_project_accessibility_model import OrgProjectAccessibilityCheckModel


class AccessiblilityAudit:
    """Engine for managing accessibility check templates and org-project scoping."""

    def upsert_master_checks_json(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Upsert master accessibility checks from JSON records.
        Uses check_code as the unique key for updates.
        """
        if not records:
            raise ValueError("No records provided for upsert")

        inserted = 0
        updated = 0
        skipped = 0

        session = SessionLocal()
        try:
            for record in records:
                check_code = record.get("check_code")
                if not check_code:
                    skipped += 1
                    continue

                check_name = record.get("check_name")
                category = record.get("category")
                default_priority = record.get("default_priority", "MEDIUM")

                if not check_name or not category:
                    skipped += 1
                    continue

                existing = session.query(MasterAccessibilityModel).filter_by(check_code=check_code).first()

                if existing:
                    existing.check_name = check_name
                    existing.description = record.get("description")
                    existing.category = category
                    existing.default_priority = default_priority
                    existing.wcag_reference = record.get("wcag_reference")
                    existing.pdfua_reference = record.get("pdfua_reference")
                    existing.remediation_guidance = record.get("remediation_guidance")
                    existing.agent_code = record.get("agent_code")
                    existing.is_active = record.get("is_active", True)
                    updated += 1
                else:
                    new_check = MasterAccessibilityModel(
                        check_code=check_code,
                        check_name=check_name,
                        description=record.get("description"),
                        category=category,
                        default_priority=default_priority,
                        wcag_reference=record.get("wcag_reference"),
                        pdfua_reference=record.get("pdfua_reference"),
                        remediation_guidance=record.get("remediation_guidance"),
                        agent_code=record.get("agent_code"),
                        is_active=record.get("is_active", True),
                    )
                    session.add(new_check)
                    inserted += 1

            session.commit()
        except Exception as exc:
            session.rollback()
            raise exc
        finally:
            session.close()

        return {
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "total": len(records),
        }

    def upload_master_checks_excel(self, file_bytes: bytes) -> dict[str, Any]:
        """
        Parse Excel file and upsert master checks.
        Expected columns: check_code, check_name, category, default_priority, ...
        """
        try:
            import openpyxl
        except ImportError as exc:
            raise ValueError("openpyxl is required for Excel parsing. Install with: pip install openpyxl") from exc

        try:
            workbook = openpyxl.load_workbook(BytesIO(file_bytes))
            worksheet = workbook.active

            rows = list(worksheet.iter_rows(values_only=True))
            if not rows:
                raise ValueError("Excel file is empty")

            headers = [str(h).strip().lower().replace(" ", "_") if h else "" for h in rows[0]]
            required_headers = ["check_code", "check_name", "category", "default_priority"]
            missing_headers = [h for h in required_headers if h not in headers]
            if missing_headers:
                raise ValueError(f"Missing required columns: {', '.join(missing_headers)}")

            records = []
            for row in rows[1:]:
                if not any(row):
                    continue

                record = {}
                for idx, header in enumerate(headers):
                    if idx < len(row):
                        record[header] = row[idx]

                records.append(record)

            return self.upsert_master_checks_json(records)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Failed to parse Excel file: {str(exc)}") from exc

    def clone_master_checks(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Clone all master accessibility checks to org-project scope.
        Payload: {organization_id: int, project_id: str | None}
        """
        organization_id = payload.get("organization_id")
        project_id = payload.get("project_id")

        if not organization_id:
            raise ValueError("organization_id is required")

        session = SessionLocal()
        try:
            org_exists = session.execute(
                text("SELECT 1 FROM organizations WHERE id = :org_id"),
                {"org_id": organization_id},
            ).fetchone()

            if not org_exists:
                raise ValueError(f"Organization {organization_id} not found")

            master_checks = session.query(MasterAccessibilityModel).filter_by(is_active=True).all()

            if not master_checks:
                raise ValueError("No active master checks found to clone")

            project_id_value = project_id if project_id else None
            inserted = 0
            updated = 0

            for master_check in master_checks:
                existing = session.query(OrgProjectAccessibilityCheckModel).filter_by(
                    organization_id=organization_id,
                    project_id=project_id_value,
                    check_code=master_check.check_code,
                ).first()

                if existing:
                    existing.check_name = master_check.check_name
                    existing.description = master_check.description
                    existing.category = master_check.category
                    existing.default_priority = master_check.default_priority
                    existing.wcag_reference = master_check.wcag_reference
                    existing.pdfua_reference = master_check.pdfua_reference
                    existing.remediation_guidance = master_check.remediation_guidance
                    existing.agent_code = master_check.agent_code
                    existing.is_active = master_check.is_active
                    updated += 1
                else:
                    new_org_check = OrgProjectAccessibilityCheckModel(
                        organization_id=organization_id,
                        project_id=project_id_value,
                        master_check_id=master_check.check_id,
                        check_code=master_check.check_code,
                        check_name=master_check.check_name,
                        description=master_check.description,
                        category=master_check.category,
                        default_priority=master_check.default_priority,
                        wcag_reference=master_check.wcag_reference,
                        pdfua_reference=master_check.pdfua_reference,
                        remediation_guidance=master_check.remediation_guidance,
                        agent_code=master_check.agent_code,
                        is_active=master_check.is_active,
                    )
                    session.add(new_org_check)
                    inserted += 1

            session.commit()

            return {
                "inserted": inserted,
                "updated": updated,
                "total": len(master_checks),
            }
        except ValueError:
            raise
        except Exception as exc:
            session.rollback()
            raise ValueError(f"Failed to clone master checks: {str(exc)}") from exc
        finally:
            session.close()

    def fetch_organization_wise_checks(self, organization_id: int) -> list[dict[str, Any]]:
        """
        Fetch all accessibility checks scoped to an organization (including project-specific).
        """
        session = SessionLocal()
        try:
            checks = session.query(OrgProjectAccessibilityCheckModel).filter_by(
                organization_id=organization_id
            ).order_by(OrgProjectAccessibilityCheckModel.id.asc()).all()

            return [
                {
                    # Keep backward-compatible key name while mapping to the actual column.
                    "check_id": check.master_check_id,
                    "org_check_id": check.id,
                    "organization_id": check.organization_id,
                    "project_id": check.project_id,
                    "check_code": check.check_code,
                    "check_name": check.check_name,
                    "description": check.description,
                    "category": check.category,
                    "default_priority": check.default_priority,
                    "wcag_reference": check.wcag_reference,
                    "pdfua_reference": check.pdfua_reference,
                    "remediation_guidance": check.remediation_guidance,
                    "agent_code": check.agent_code,
                    "is_active": check.is_active,
                }
                for check in checks
            ]
        except Exception as exc:
            raise ValueError(f"Failed to fetch organization-wise checks: {str(exc)}") from exc
        finally:
            session.close()
