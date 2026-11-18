"""
StructTreeExplorer - Comprehensive document structure tree extraction and analysis.

Provides utilities to traverse and extract the complete hierarchical structure of a PDF document,
producing JSON-compatible output suitable for tree UI visualization.

Key Features:
- Full recursive traversal of document structure tree
- Support for all element types (Document, H1-H6, P, Figure, Table, List, etc.)
- Extracts element properties (text, alt text, ID, page number, etc.)
- Output compatible with tree UI visualization
- Caching to avoid repeated tree traversals
- Optional depth limiting and filtering

Usage:
    explorer = StructTreeExplorer(pdf_doc)
    tree_json = explorer.get_tree_structure()
    
    # For UI display:
    tree_json = {
        "type": "Document",
        "children": [
            {"type": "H1", "text": "Title", ...},
            {"type": "P", "text": "Paragraph text", ...},
            ...
        ]
    }
"""

from __future__ import annotations
from typing import Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum


class ElementType(Enum):
    """Standard PDF structure element types."""
    DOCUMENT = "Document"
    SECTION = "Sect"
    DIV = "Div"
    BLOCK_QUOTE = "BlockQuote"
    
    # Headings
    H1 = "H1"
    H2 = "H2"
    H3 = "H3"
    H4 = "H4"
    H5 = "H5"
    H6 = "H6"
    
    # Content
    PARAGRAPH = "P"
    SPAN = "Span"
    LINK = "Link"
    
    # Lists
    LIST = "L"
    LIST_ITEM = "LI"
    LIST_ITEM_LABEL = "Lbl"
    LIST_ITEM_BODY = "LBody"
    
    # Tables
    TABLE = "Table"
    TABLE_ROW = "TR"
    TABLE_HEADER_CELL = "TH"
    TABLE_DATA_CELL = "TD"
    TABLE_HEAD = "THead"
    TABLE_BODY = "TBody"
    TABLE_FOOT = "TFoot"
    
    # Media
    FIGURE = "Figure"
    FORMULA = "Formula"
    
    # Other
    ARTIFACT = "Artifact"


@dataclass
class StructElement:
    """Represents a single element in the structure tree."""
    type: str
    children: list[StructElement] | None = None
    text: str | None = None
    alt: str | None = None
    id: str | None = None
    page_no: int | None = None
    language: str | None = None
    
    # Optional metadata for specific element types
    href: str | None = None  # For links
    title: str | None = None  # For sections
    row_index: int | None = None  # For table cells
    col_index: int | None = None  # For table cells
    row_span: int | None = None  # For table cells
    col_span: int | None = None  # For table cells
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values and empty lists."""
        result = {"type": self.type}
        
        if self.text:
            result["text"] = self.text
        if self.alt:
            result["alt"] = self.alt
        if self.id:
            result["id"] = self.id
        if self.page_no is not None:
            result["page_no"] = self.page_no
        if self.language:
            result["language"] = self.language
        if self.href:
            result["href"] = self.href
        if self.title:
            result["title"] = self.title
        if self.row_index is not None:
            result["row_index"] = self.row_index
        if self.col_index is not None:
            result["col_index"] = self.col_index
        if self.row_span is not None and self.row_span > 1:
            result["row_span"] = self.row_span
        if self.col_span is not None and self.col_span > 1:
            result["col_span"] = self.col_span
            
        if self.children:
            result["children"] = [child.to_dict() for child in self.children]
            
        return result


class StructTreeExplorer:
    """Comprehensive PDF structure tree traversal and extraction."""
    
    def __init__(self, pdf_doc, max_depth: int | None = None, cache: dict | None = None):
        """
        Initialize the structure tree explorer.
        
        Args:
            pdf_doc: PDFix PdfDoc object (opened and ready)
            max_depth: Maximum traversal depth (None for unlimited)
            cache: Optional cache dictionary for shared state across explorations
        """
        self.pdf_doc = pdf_doc
        self.max_depth = max_depth
        self.cache = cache or {}
        self._element_cache = {}
        self._extracted = False
        self._root_element = None
    
    def get_tree_structure(self) -> dict[str, Any]:
        """
        Extract complete document structure tree as JSON-compatible dictionary.
        
        Returns:
            Dictionary with "type": "Document" and "children" array of all elements.
            Format suitable for tree UI visualization.
            
        Example:
            {
                "type": "Document",
                "children": [
                    {"type": "H1", "text": "Title"},
                    {"type": "P", "text": "Paragraph..."},
                    ...
                ]
            }
        """
        if not self._extracted:
            self._extract_tree()
        
        if self._root_element:
            return self._root_element.to_dict()
        return {"type": "Document", "children": []}
    
    def get_elements_by_type(self, element_type: str) -> list[StructElement]:
        """
        Get all elements of a specific type from the structure tree.
        
        Args:
            element_type: Element type to filter by (e.g., "H1", "Figure", "Table")
            
        Returns:
            List of matching StructElement objects
        """
        if not self._extracted:
            self._extract_tree()
        
        results = []
        
        def find_type(element: StructElement):
            if element.type == element_type:
                results.append(element)
            if element.children:
                for child in element.children:
                    find_type(child)
        
        if self._root_element:
            find_type(self._root_element)
        
        return results
    
    def get_flat_element_list(self) -> list[dict[str, Any]]:
        """
        Get all elements as a flat list with hierarchical information.
        Useful for searching or filtering without nested traversal.
        
        Returns:
            List of dictionaries with element info and depth/parent info
        """
        flat_list = []
        
        def flatten(element: StructElement, depth: int = 0, parent_type: str | None = None):
            item = element.to_dict()
            item["depth"] = depth
            if parent_type:
                item["parent_type"] = parent_type
            flat_list.append(item)
            
            if element.children:
                for child in element.children:
                    flatten(child, depth + 1, element.type)
        
        if self._root_element:
            flatten(self._root_element)
        
        return flat_list
    
    def get_tree_statistics(self) -> dict[str, Any]:
        """
        Get statistics about the document structure.
        
        Returns:
            Dictionary with element counts, depths, and type distribution
        """
        if not self._extracted:
            self._extract_tree()
        
        flat_list = self.get_flat_element_list()
        
        type_counts = {}
        max_depth = 0
        total_elements = len(flat_list)
        
        for item in flat_list:
            elem_type = item.get("type")
            type_counts[elem_type] = type_counts.get(elem_type, 0) + 1
            max_depth = max(max_depth, item.get("depth", 0))
        
        return {
            "total_elements": total_elements,
            "max_depth": max_depth,
            "element_types": sorted(type_counts.keys()),
            "type_counts": type_counts,
        }
    
    def _extract_tree(self) -> None:
        """Extract complete structure tree from PDF document."""
        try:
            struct_tree = self.pdf_doc.GetStructTree() if hasattr(self.pdf_doc, "GetStructTree") else None
            if not struct_tree:
                self._root_element = StructElement(type="Document", children=[])
                self._extracted = True
                return
            
            # Create root element
            root_element = StructElement(
                type="Document",
                children=[]
            )
            
            # Traverse structure tree
            def traverse(node, parent_element: StructElement, depth: int = 0) -> None:
                """Recursively traverse structure tree."""
                if self.max_depth is not None and depth >= self.max_depth:
                    return
                
                try:
                    num_children = node.GetNumChildren() if hasattr(node, "GetNumChildren") else 0
                    
                    for i in range(num_children):
                        child = node.GetChildObject(i) if hasattr(node, "GetChildObject") else None
                        if not child:
                            continue
                        
                        # Extract element properties
                        struct_elem = self._extract_element_data(child)
                        if struct_elem:
                            parent_element.children = parent_element.children or []
                            parent_element.children.append(struct_elem)
                            
                            # Recursively process children
                            if hasattr(child, "GetNumChildren"):
                                traverse(child, struct_elem, depth + 1)
                
                except Exception:
                    pass
            
            traverse(struct_tree, root_element)
            self._root_element = root_element
            self._extracted = True
            
        except Exception:
            self._root_element = StructElement(type="Document", children=[])
            self._extracted = True
    
    def _extract_element_data(self, element) -> StructElement | None:
        """
        Extract data from a single structure element.
        
        Args:
            element: PDFix structure element object
            
        Returns:
            StructElement with extracted properties, or None if extraction fails
        """
        try:
            element_type = element.GetType() if hasattr(element, "GetType") else ""
            if not element_type:
                return None
            
            # Basic properties
            struct_elem = StructElement(type=element_type)
            
            # Extract text content
            if hasattr(element, "GetText"):
                try:
                    text = element.GetText()
                    struct_elem.text = text.strip() if text else None
                except Exception:
                    pass
            
            # Extract alt text (for figures, graphics, etc.)
            if hasattr(element, "GetAlt"):
                try:
                    alt = element.GetAlt()
                    struct_elem.alt = alt if alt else None
                except Exception:
                    pass
            
            # Extract element ID
            if hasattr(element, "GetId"):
                try:
                    elem_id = element.GetId()
                    struct_elem.id = elem_id if elem_id else None
                except Exception:
                    pass
            
            # Extract page number
            if hasattr(element, "GetPageNumber"):
                try:
                    page_no = element.GetPageNumber()
                    struct_elem.page_no = page_no if page_no is not None else None
                except Exception:
                    pass
            
            # Extract language if available
            if hasattr(element, "GetLang"):
                try:
                    lang = element.GetLang()
                    struct_elem.language = lang if lang else None
                except Exception:
                    pass
            
            # Extract link URL (for Link elements)
            if element_type == "Link" and hasattr(element, "GetHyperlink"):
                try:
                    href = element.GetHyperlink()
                    struct_elem.href = href if href else None
                except Exception:
                    pass
            
            # Extract title/caption (for sections, figures)
            if hasattr(element, "GetTitle"):
                try:
                    title = element.GetTitle()
                    struct_elem.title = title if title else None
                except Exception:
                    pass
            
            # Extract table cell properties
            if element_type in ("TH", "TD"):
                # Try to extract row/column indices if available
                if hasattr(element, "GetRowIndex"):
                    try:
                        struct_elem.row_index = element.GetRowIndex()
                    except Exception:
                        pass
                
                if hasattr(element, "GetColIndex"):
                    try:
                        struct_elem.col_index = element.GetColIndex()
                    except Exception:
                        pass
                
                if hasattr(element, "GetRowSpan"):
                    try:
                        struct_elem.row_span = element.GetRowSpan()
                    except Exception:
                        pass
                
                if hasattr(element, "GetColSpan"):
                    try:
                        struct_elem.col_span = element.GetColSpan()
                    except Exception:
                        pass
            
            return struct_elem
            
        except Exception:
            return None


def explore_document_structure(pdf_doc, max_depth: int | None = None) -> dict[str, Any]:
    """
    Convenience function to quickly extract document structure.
    
    Args:
        pdf_doc: PDFix PdfDoc object
        max_depth: Optional maximum traversal depth
        
    Returns:
        Dictionary with complete document structure
    """
    explorer = StructTreeExplorer(pdf_doc, max_depth=max_depth)
    return explorer.get_tree_structure()


def get_structure_statistics(pdf_doc) -> dict[str, Any]:
    """
    Get quick statistics about document structure.
    
    Args:
        pdf_doc: PDFix PdfDoc object
        
    Returns:
        Dictionary with structure statistics
    """
    explorer = StructTreeExplorer(pdf_doc)
    return explorer.get_tree_statistics()
