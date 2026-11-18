"""
ppt_accessibility_remediation_pipeline.py
=========================================
Orchestrates PPT accessibility REMEDIATION end to end:

    open .pptx  ->  validate  ->  dispatch each actionable issue to the
    remediation agent that owns its rule  ->  save  ->  re-validate  ->  report.

The report lists, per run:
    issues_fixed   — issues that were FAIL/WARNING before and are clean after
    issues_failed  — issues still FAIL/WARNING after (with the reason / captured
                     agent error, or "no remediation available")
    remediation_results — what each agent did (RemediationResult per attempt)

Robustness
----------
Every agent call is isolated in try/except: if one agent raises, its exception
message is captured into a failed RemediationResult and the pipeline CONTINUES
with the remaining agents. Registry build, validation, save and re-validation are
all guarded too, so the pipeline always returns a report rather than raising.
"""
from __future__ import annotations

import logging
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

try:
    from pptx import Presentation
except Exception:                       # pragma: no cover
    Presentation = None

try:
    from src.modules.accessibility_ppt.engine.ppt_remediator.base_remediation_agent import (
        RemediationResult,
    )
except Exception:                       # pragma: no cover - fallback shape
    from dataclasses import dataclass, field

    @dataclass
    class RemediationResult:            # type: ignore
        rule_id: str
        agent_name: str
        success: bool
        action: str
        changes_made: list = field(default_factory=list)
        error: str | None = None

logger = logging.getLogger(__name__)

_ACTIONABLE = ("FAIL", "WARNING")

# (module, class) for each remediation agent — imported defensively so one bad
# import never disables the whole pipeline.
_AGENT_SPECS = [
    ("altText_remediation_agent", "AltTextRemediationAgent"),
    ("color_contrast_remediation_agent", "ColorContrastRemediationAgent"),
    ("hyperlink_remediation_agent", "HyperlinkRemediationAgent"),
    ("language_remediation_agent", "LanguageRemediationAgent"),
    ("metadata_remediation_agent", "MetadataRemediationAgent"),
    ("reading_order_remediation_agent", "ReadingOrderRemediationAgent"),
    ("table_remediation_agent", "TableRemediationAgent"),
    ("text_remediation_agent", "TextRemediationAgent"),
    ("title_remediation_agent", "TitleRemediationAgent"),
]
_PKG = "src.modules.accessibility_ppt.engine.ppt_remediator"


def _build_registry(agents: list | None = None):
    """Return (rule_id -> agent, [agents]). Import errors are isolated."""
    instances = list(agents) if agents else []
    if not instances:
        for mod, cls in _AGENT_SPECS:
            try:
                m = __import__(f"{_PKG}.{mod}", fromlist=[cls])
                instances.append(getattr(m, cls)())
            except Exception as exc:
                logger.warning("PPT remediator '%s' unavailable: %s", cls, exc)
    registry: dict[str, Any] = {}
    for inst in instances:
        for rule in getattr(inst, "supported_rules", set()) or set():
            registry.setdefault(rule, inst)
    return registry, instances


class PPTRemediationPipeline:
    """End-to-end PPT accessibility remediation."""

    def __init__(self, validator: Callable[[str], dict] | None = None,
                 agents: list | None = None):
        # validator(path) -> validation-result dict (agent_results + score).
        # Injectable for testing; defaults to the PPT validation orchestrator.
        self._validator = validator
        self._registry, self._agents = _build_registry(agents)

    # ------------------------------------------------------------- validation
    def _validate(self, path: str, organization_id, project_id) -> dict:
        if self._validator is not None:
            return self._validator(path)
        from src.modules.accessibility_ppt.engine.ppt_accesibility_engine_pipeline import (
            PPTValidationOrchestrator,
        )
        return PPTValidationOrchestrator().validate(
            path, organization_id=organization_id, project_id=project_id)

    @staticmethod
    def _status_map(vres: dict) -> dict[str, dict]:
        """rule_id -> issue dict, gathered from every agent's results."""
        out: dict[str, dict] = {}
        for ar in (vres or {}).get("agent_results", []) or []:
            for iss in ar.get("issues", []) or []:
                rid = iss.get("rule_id")
                if rid:
                    out[rid] = iss
        return out

    # ------------------------------------------------------------------- run
    def run(self, pptx_path: str, output_path: str | None = None,
            organization_id: int | None = None, project_id: str | None = None,
            context_extra: dict | None = None) -> dict:
        report: dict[str, Any] = {
            "status": "completed",
            "document_name": Path(pptx_path).name,
            "remediated_path": None,
            "summary": {},
            "issues_fixed": [],
            "issues_failed": [],
            "remediation_results": [],
            "errors": [],
        }
        if Presentation is None:
            report["status"] = "failed"
            report["errors"].append("python-pptx is not installed")
            return report

        # 1) open the deck
        try:
            prs = Presentation(pptx_path)
        except Exception as exc:
            report["status"] = "failed"
            report["errors"].append(f"could not open presentation: {exc}")
            return report

        # 2) initial validation
        try:
            initial = self._validate(pptx_path, organization_id, project_id)
        except Exception as exc:
            initial = {}
            report["errors"].append(f"initial validation failed: {exc}")
            logger.exception("PPT initial validation failed")
        before = self._status_map(initial)
        actionable_before = {r: i for r, i in before.items()
                             if i.get("status") in _ACTIONABLE}

        # 3) shared remediation context (live Presentation, mutated in place)
        context: dict[str, Any] = {
            "presentation": prs,
            "pptx_path": str(pptx_path),
            "document_name": Path(pptx_path).name,
        }
        if context_extra:
            context.update(context_extra)

        # 4) dispatch — one call per unique actionable rule that has an agent.
        #    Each call is isolated: a crash is captured and the loop continues.
        rem_errors: dict[str, str] = {}
        for rule in sorted(r for r in actionable_before if r in self._registry):
            agent = self._registry[rule]
            name = getattr(agent, "agent_name", agent.__class__.__name__)
            try:
                res = agent.remediate(dict(actionable_before[rule]), context)
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                logger.exception("PPT remediation agent '%s' crashed on %s", name, rule)
                report["errors"].append(f"{name} on {rule}: {msg}")
                res = RemediationResult(rule_id=rule, agent_name=name, success=False,
                                        action="error", changes_made=[],
                                        error=msg + " | " + traceback.format_exc(limit=2))
            try:
                report["remediation_results"].append(asdict(res))
            except Exception:
                report["remediation_results"].append({
                    "rule_id": rule, "agent_name": name,
                    "success": getattr(res, "success", False),
                    "action": getattr(res, "action", "?"),
                    "changes_made": getattr(res, "changes_made", []),
                    "error": getattr(res, "error", None)})
            if getattr(res, "error", None):
                rem_errors[rule] = res.error

        # 5) save the remediated deck
        out = output_path or self._default_out(pptx_path)
        try:
            prs.save(out)
            report["remediated_path"] = out
        except Exception as exc:
            report["status"] = "failed"
            report["errors"].append(f"could not save remediated presentation: {exc}")
            return report

        # 6) re-validate the saved deck
        try:
            final = self._validate(out, organization_id, project_id)
        except Exception as exc:
            final = {}
            report["errors"].append(f"final validation failed: {exc}")
            logger.exception("PPT final validation failed")
        after = self._status_map(final)
        actionable_after = {r for r, i in after.items()
                            if i.get("status") in _ACTIONABLE}

        # 7) classify fixed vs still-failed
        for rule, iss in actionable_before.items():
            entry = {"rule_id": rule, "category": iss.get("category"),
                     "severity": iss.get("severity"), "message": iss.get("message")}
            still_failing = rule in actionable_after
            if still_failing:
                entry["remediation_error"] = (
                    rem_errors.get(rule)
                    or (None if rule in self._registry else "no remediation available"))
                report["issues_failed"].append(entry)
            else:
                report["issues_fixed"].append(entry)

        report["summary"] = {
            "issues_before": len(actionable_before),
            "issues_fixed": len(report["issues_fixed"]),
            "issues_failed": len(report["issues_failed"]),
            "issues_remaining": len(actionable_after),
            "regressions": sorted(actionable_after - set(actionable_before)),
            "agents_run": len(report["remediation_results"]),
            "agents_errored": sum(1 for r in report["remediation_results"]
                                  if not r.get("success")),
            "score_before": (initial.get("accessibility_score") or {}).get("overall"),
            "score_after": (final.get("accessibility_score") or {}).get("overall"),
        }
        return report

    @staticmethod
    def _default_out(pptx_path: str) -> str:
        p = str(pptx_path)
        return (p[:-5] + "_remediated.pptx" if p.lower().endswith(".pptx")
                else p + "_remediated.pptx")


def remediate_pptx(pptx_path: str, output_path: str | None = None,
                   organization_id: int | None = None, project_id: str | None = None,
                   context_extra: dict | None = None) -> dict:
    """Convenience one-shot entry point."""
    return PPTRemediationPipeline().run(
        pptx_path, output_path=output_path, organization_id=organization_id,
        project_id=project_id, context_extra=context_extra)
