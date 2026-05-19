from src.modules.submit_plus.engines.base_engine import BaseEngine
from src.core.logger import get_logger
import json

logger = get_logger(__name__)

class StructureEngine(BaseEngine):
    """
    Stateless engine for validating document structure against template.
    Analyzes if content matches the required structure template.
    
    This engine has NO database dependencies.
    """

    def run(self, data: dict):
        """
        Validate manuscript structure against template.
        
        Args:
            data: Dictionary containing:
                - content_extraction: extraction results with content
                - template: template info with structure_json
            
        Returns:
            Dictionary with structure validation results
        """
        
        # Get content
        content = data.get("content_extraction", {}).get("content")
        if not content:
            return {
                "structure_score": 0.0,
                "analysis": "No content provided",
                "sections_found": [],
                "sections_missing": [],
                "order_correct": False,
                "completeness_percentage": 0,
                "issues": ["Empty manuscript"]
            }
        
        if not isinstance(content, str):
            return {
                "structure_score": 0.0,
                "analysis": "Content must be a text string",
                "sections_found": [],
                "sections_missing": [],
                "order_correct": False,
                "completeness_percentage": 0,
                "issues": ["Invalid content format"]
            }
        
        # Get template
        template = data.get("template")
        if not template:
            return {
                "structure_score": 0.0,
                "analysis": "No template provided",
                "sections_found": [],
                "sections_missing": [],
                "order_correct": False,
                "completeness_percentage": 0,
                "issues": ["No structure template available"]
            }
        
        # Parse template sections
        structure_json = template.get("structure_json")
        if isinstance(structure_json, str):
            try:
                required_sections = json.loads(structure_json)
            except json.JSONDecodeError:
                required_sections = structure_json.split(',')
                required_sections = [s.strip() for s in required_sections]
        else:
            required_sections = structure_json if isinstance(structure_json, list) else []
        
        if not required_sections:
            return {
                "structure_score": 0.0,
                "analysis": "Template has no sections defined",
                "sections_found": [],
                "sections_missing": [],
                "order_correct": False,
                "completeness_percentage": 0,
                "issues": ["Invalid template structure"]
            }
        
        # Search for sections in content (case-insensitive)
        content_lower = content.lower()
        sections_found = []
        sections_found_positions = {}
        issues = []
        
        for section in required_sections:
            section_lower = section.lower()
            if section_lower in content_lower:
                sections_found.append(section)
                sections_found_positions[section] = content_lower.find(section_lower)
            else:
                issues.append(f"Missing section: {section}")
        
        # Calculate completeness
        completeness_percentage = (len(sections_found) / len(required_sections)) * 100
        
        # Check if sections are in correct order
        order_correct = self._check_order(sections_found, required_sections, sections_found_positions)
        if not order_correct and len(sections_found) > 1:
            issues.append("Sections are not in the correct order")
        
        # Calculate structure score
        structure_score = self._calculate_score(
            completeness_percentage,
            order_correct,
            len(sections_found),
            len(required_sections)
        )
        
        # Determine missing sections
        sections_missing = [s for s in required_sections if s not in sections_found]
        
        return {
            "structure_score": round(structure_score, 2),
            "analysis": f"Structure validation: {len(sections_found)}/{len(required_sections)} sections found",
            "sections_found": sections_found,
            "sections_missing": sections_missing,
            "order_correct": order_correct,
            "completeness_percentage": round(completeness_percentage, 2),
            "issues": issues if issues else ["All sections present and in correct order"]
        }
    
    def _check_order(self, sections_found, required_sections, positions):
        """
        Check if found sections are in the correct order.
        """
        if len(sections_found) <= 1:
            return True
        
        # Get indices of found sections in the required order
        found_indices = [required_sections.index(s) for s in sections_found if s in required_sections]
        
        # Check if indices are in ascending order
        for i in range(1, len(found_indices)):
            if found_indices[i] <= found_indices[i-1]:
                return False
        
        return True
    
    def _calculate_score(self, completeness_percentage, order_correct, sections_found_count, total_sections):
        """
        Calculate overall structure score (0-1).
        """
        # Base score: completeness (0-0.7)
        completeness_score = (completeness_percentage / 100) * 0.7
        
        # Order bonus (0-0.3)
        order_score = 0.3 if order_correct else 0.0
        
        # Total score
        total_score = completeness_score + order_score
        
        return max(0.0, min(1.0, total_score))