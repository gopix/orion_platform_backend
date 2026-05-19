from src.modules.submit_plus.models.editor_analysis_model import EditorAnalysisResult
from src.core.logger import get_logger

logger = get_logger(__name__)
def save_analysis_result(db, manuscript_id: int, result: dict):
    logger.info(f"DEBUG: Saving analysis for manuscript_id: {manuscript_id}")
    analysis = EditorAnalysisResult(
        manuscript_id=manuscript_id,
        analysis_json=result
    )
    logger.info("Saving analysis result...")
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    return analysis