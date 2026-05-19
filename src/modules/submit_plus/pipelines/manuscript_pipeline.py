import os
import docx

from src.modules.submit_plus.engines.aggregator import ManuscriptAggregator
from src.modules.submit_plus.engines.originality.originality_engine import OriginalityEngine
from src.modules.submit_plus.engines.ai_authorship_engine import AIAuthorshipEngine
from src.modules.submit_plus.engines.editorial_engine import EditorialEngine
from src.modules.submit_plus.engines.structure_engine import StructureEngine    
from src.modules.submit_plus.engines.redundancy_engine import RedundancyEngine
from src.modules.submit_plus.engines.scoring_engine import ScoringEngine
from src.modules.submit_plus.services.analysis_service import save_analysis_result
from src.modules.submit_plus.engines.content_extractor_engine import ContentExtractorEngine
from src.core.logger import get_logger

logger = get_logger(__name__)

class ManuscriptPipeline:

    
    def run(self, manuscript_detail: dict):
        """
        Pipeline orchestrator that processes a manuscript through various analysis engines.
        All database operations are handled by service layer.
        All engines are stateless and work only with content.
        
        Args:
            manuscript_id: ID of the manuscript to process
            db: Database session from service layer
        """

        print(f"\n{'='*80}")
        print(f"PIPELINE STARTED: Manuscript ID = {manuscript_detail['manuscript_id']}")
        print(f"{'='*80}\n")
        
        # ======== Step 0: Fetch manuscript content ========
        print(f"{'='*80}")
        print(f"[0/7] FETCHING MANUSCRIPT DATA")
        print(f"{'='*80}")
        final_result = {}
        content_extraction = ContentExtractorEngine().run({"file_path": manuscript_detail.get("file_path")})
        
        if content_extraction["status"] != "success":
            print(f"ERROR: {content_extraction['message']}")
            print(f"{'='*80}\n")
            return {
                "status": "error",
                "message": content_extraction["message"],
                "manuscript_id": manuscript_detail['manuscript_id']
            }
        else:
            content_extraction_result = {}
            content_extraction_result["file_type"] = content_extraction.get("file_type", "unknown")
            content_extraction_result["file_path"] = content_extraction.get("file_path", "")
            content_extraction_result["word_count"] = content_extraction.get("word_count", 0)
            content_extraction_result["character_count"] = content_extraction.get("character_count", 0)
            
            #print(f"Content extraction: {content_extraction}")

        final_result["content_extraction"] = content_extraction_result

        manuscript_detail["content_extraction"] = content_extraction
       
        
        try:
            # ======== Stage 1: Structure Validation ========
            print(f"{'-'*80}")
            print(f"[1/7] STRUCTURE ENGINE")
            print(f"{'-'*80}")
            structure = StructureEngine().run(manuscript_detail)
            final_result["STRUCTURE ENGINE ANALYSIS"] = structure

            print(f"***final_result:Stage 1***: {final_result}")

            # ======== Stage 2: Originality Analysis ========
            print(f"{'-'*80}")
            print(f"[2/7] ORIGINALITY ENGINE")
            print(f"{'-'*80}")
            originality = OriginalityEngine().run(manuscript_detail)
            final_result["originality"] = originality
            print(f"***final_result:Stage 2***: {final_result}")
            
            # ======== Stage 3: AI Authorship Detection ========
            print(f"{'-'*80}")
            print(f"[3/7] AI AUTHORSHIP ENGINE")
            print(f"{'-'*80}")
            ai_authorship = AIAuthorshipEngine().run(manuscript_detail)
            final_result["ai_authorship"] = ai_authorship
            print(f"***final_result:Stage 3***: {final_result}")
            
            # ======== Stage 4: Editorial Analysis ========
            print(f"{'-'*80}")
            print(f"[4/7] EDITORIAL ENGINE")
            print(f"{'-'*80}")
            editorial = EditorialEngine().run(manuscript_detail)
            final_result["editorial"] = editorial
            print(f"***final_result:Stage 4***: {final_result}")
            
            
            # ======== Stage 5: Redundancy Check ========
            print(f"{'-'*80}")
            print(f"[5/7] REDUNDANCY ENGINE")
            print(f"{'-'*80}")
            redundancy = RedundancyEngine().run(manuscript_detail)
            final_result["redundancy"] = redundancy
            print(f"***final_result:Stage 5***: {final_result}")

            # ======== Stage 6: Scoring Aggregation ========
            print(f"{'-'*80}")
            print(f"[6/7] SCORING ENGINE")
            print(f"{'-'*80}")
                       
            scoring = ScoringEngine().run({
                "originality": originality,
                "ai": ai_authorship,
                "editorial": editorial,
                "structure": structure,
                "redundancy": redundancy
            })
            
            final_result["scoring"] = scoring
            score = scoring.get('final_score', 'N/A')
            print(f"Result: {score}\n")
            print(f"***final_result:Stage 6***: {final_result}")            

            # ======== Stage 7: Aggregation & Storage ========
            print(f"{'='*80}")
            print(f"[7/7] AGGREGATING & STORING RESULTS")
            print(f"{'='*80}")
            '''
            aggregator = ManuscriptAggregator()
            final_result = aggregator.build(final_result)
            
            # Service layer handles database storage
            save_analysis_result(manuscript_detail['manuscript_id'], final_result)
            print(f"Results saved successfully\n")
            '''
            print(f"{'='*80}")
            print(f"PIPELINE COMPLETED SUCCESSFULLY")
            print(f"{'='*80}\n")
            return ""
            
        except Exception as e:
            logger.error(f"Pipeline failed for manuscript_id={manuscript_detail['manuscript_id']}: {str(e)}", exc_info=True)
            print(f"\n{'='*80}")
            print(f"ERROR: Pipeline failed - {str(e)}")
            print(f"{'='*80}\n")
            raise


    