from typing import List, Optional


class SubmitPayload:
    def __init__(self, title: str, author: str, organization_id: int, file):
        self.title = title
        self.author = author
        self.organization_id = organization_id
        self.file = file


class StructureTemplatePayload:
    def __init__(self, organization_id: int, template_name: str, structure: List[str], book_id: Optional[int] = None):
        self.organization_id = organization_id
        self.book_id = book_id
        self.template_name = template_name
        self.structure = structure