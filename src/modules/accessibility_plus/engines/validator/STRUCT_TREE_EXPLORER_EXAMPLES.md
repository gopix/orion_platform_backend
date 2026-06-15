"""
StructTree Explorer - Usage Examples and Integration Guide

This document provides practical examples of how to use the StructTree Explorer
for document structure extraction and visualization.
"""

# ============================================================================
# EXAMPLE 1: Basic Tree Extraction for UI Display
# ============================================================================

"""
Simple integration with existing PDF processing:
"""

from src.modules.accessibility_plus.engines.validator.structure_tree_explorer import (
    StructTreeExplorer,
    explore_document_structure,
)


def get_document_tree_for_ui(pdf_doc):
    """Extract full document structure for tree UI visualization."""
    explorer = StructTreeExplorer(pdf_doc)
    tree_json = explorer.get_tree_structure()
    return tree_json


# Output example:
# {
#   "type": "Document",
#   "children": [
#       {
#           "type": "H1",
#           "text": "Accessibility Remediation",
#           "page_no": 1
#       },
#       {
#           "type": "H2",
#           "text": "Sample Test Document",
#           "page_no": 1
#       },
#       {
#           "type": "P",
#           "text": "This document...",
#           "page_no": 1
#       },
#       {
#           "type": "Figure",
#           "alt": "",
#           "page_no": 2
#       },
#       {
#           "type": "L",
#           "children": [
#               {
#                   "type": "LI",
#                   "text": "List item 1"
#               },
#               {
#                   "type": "LI",
#                   "text": "List item 2"
#               }
#           ]
#       },
#       {
#           "type": "Table",
#           "children": [
#               {
#                   "type": "TR",
#                   "children": [
#                       {"type": "TH", "text": "Header 1", "col_index": 0},
#                       {"type": "TH", "text": "Header 2", "col_index": 1}
#                   ]
#               },
#               {
#                   "type": "TR",
#                   "children": [
#                       {"type": "TD", "text": "Cell 1", "row_index": 1, "col_index": 0},
#                       {"type": "TD", "text": "Cell 2", "row_index": 1, "col_index": 1}
#                   ]
#               }
#           ]
#       }
#   ]
# }


# ============================================================================
# EXAMPLE 2: Get Structure Statistics
# ============================================================================

def analyze_document_structure(pdf_doc):
    """Analyze and report on document structure complexity."""
    explorer = StructTreeExplorer(pdf_doc)
    stats = explorer.get_tree_statistics()
    
    print(f"Total elements: {stats['total_elements']}")
    print(f"Max depth: {stats['max_depth']}")
    print(f"Element types: {sorted(stats['element_types'])}")
    print(f"Type distribution: {stats['type_counts']}")
    
    return stats


# ============================================================================
# EXAMPLE 3: Search and Filter Elements
# ============================================================================

def find_all_headings(pdf_doc):
    """Find all heading elements in document."""
    explorer = StructTreeExplorer(pdf_doc)
    
    headings = []
    for heading_type in ["H1", "H2", "H3", "H4", "H5", "H6"]:
        headings.extend(explorer.get_elements_by_type(heading_type))
    
    return [h.to_dict() for h in headings]


def find_all_figures_with_alt(pdf_doc):
    """Find all figures and check which ones have alt text."""
    explorer = StructTreeExplorer(pdf_doc)
    figures = explorer.get_elements_by_type("Figure")
    
    results = {
        "total": len(figures),
        "with_alt": [],
        "without_alt": [],
    }
    
    for fig in figures:
        fig_dict = fig.to_dict()
        if fig.alt and fig.alt.strip():
            results["with_alt"].append(fig_dict)
        else:
            results["without_alt"].append(fig_dict)
    
    return results


def find_all_tables(pdf_doc):
    """Find all tables in document."""
    explorer = StructTreeExplorer(pdf_doc)
    tables = explorer.get_elements_by_type("Table")
    return [t.to_dict() for t in tables]


# ============================================================================
# EXAMPLE 4: Use in Validation Agent
# ============================================================================

"""
Integration with TreeStructureAgent for pipeline:
"""

def extract_tree_via_agent(pdf_doc, pdf_path):
    """Extract tree using the agent framework."""
    from src.modules.accessibility_plus.engines.validator.tree_structure_agent import (
        TreeStructureAgent,
    )
    
    agent = TreeStructureAgent()
    context = {
        "pdf_doc": pdf_doc,
        "pdf_doc_path": pdf_path,
        "organization_id": 123,
        "project_id": "proj-001",
    }
    
    # Get full tree structure
    result = agent.run_check("TREE-001", context)
    tree_structure = result.value
    
    # Get statistics
    stats_result = agent.run_check("TREE-002", context)
    statistics = stats_result.value
    
    # Get flat list for searching
    flat_result = agent.run_check("TREE-003", context)
    flat_list = flat_result.value["elements"]
    
    return tree_structure, statistics, flat_list


# ============================================================================
# EXAMPLE 5: Flat List for Searching/Filtering
# ============================================================================

def search_elements_by_text(pdf_doc, search_text):
    """Search for elements containing specific text."""
    explorer = StructTreeExplorer(pdf_doc)
    flat_list = explorer.get_flat_element_list()
    
    results = [
        elem for elem in flat_list
        if elem.get("text") and search_text.lower() in elem["text"].lower()
    ]
    
    return results


def get_elements_by_depth(pdf_doc, depth):
    """Get all elements at a specific depth level."""
    explorer = StructTreeExplorer(pdf_doc)
    flat_list = explorer.get_flat_element_list()
    
    return [elem for elem in flat_list if elem.get("depth") == depth]


# ============================================================================
# EXAMPLE 6: Limited Depth Traversal (for performance)
# ============================================================================

def get_top_level_structure(pdf_doc, max_depth=3):
    """Get only the top 3 levels of document structure (for quick preview)."""
    explorer = StructTreeExplorer(pdf_doc, max_depth=max_depth)
    tree = explorer.get_tree_structure()
    return tree


# ============================================================================
# EXAMPLE 7: Integration with UI/API Response
# ============================================================================

def prepare_tree_response(pdf_doc, pdf_path, include_stats=True):
    """Prepare a complete response for the UI with tree and optional stats."""
    explorer = StructTreeExplorer(pdf_doc)
    
    response = {
        "status": "success",
        "document": pdf_path,
        "tree": explorer.get_tree_structure(),
    }
    
    if include_stats:
        response["statistics"] = explorer.get_tree_statistics()
    
    return response


# ============================================================================
# EXAMPLE 8: Tree Traversal for Custom Processing
# ============================================================================

def count_elements_by_type(pdf_doc):
    """Count elements of each type in document."""
    explorer = StructTreeExplorer(pdf_doc)
    
    type_counts = {}
    flat_list = explorer.get_flat_element_list()
    
    for elem in flat_list:
        elem_type = elem.get("type")
        type_counts[elem_type] = type_counts.get(elem_type, 0) + 1
    
    return type_counts


def get_accessibility_audit_summary(pdf_doc):
    """Generate accessibility audit summary from structure."""
    explorer = StructTreeExplorer(pdf_doc)
    stats = explorer.get_tree_statistics()
    flat_list = explorer.get_flat_element_list()
    
    # Analyze structure for accessibility
    summary = {
        "total_elements": stats["total_elements"],
        "max_depth": stats["max_depth"],
        "headings": len([e for e in flat_list if e["type"].startswith("H")]),
        "images": len([e for e in flat_list if e["type"] == "Figure"]),
        "tables": len([e for e in flat_list if e["type"] == "Table"]),
        "lists": len([e for e in flat_list if e["type"] == "L"]),
        "links": len([e for e in flat_list if e["type"] == "Link"]),
        "images_without_alt": len([
            e for e in flat_list 
            if e["type"] == "Figure" and not e.get("alt")
        ]),
    }
    
    return summary
