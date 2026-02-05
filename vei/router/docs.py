from __future__ import annotations

from typing import Dict, List, Optional

from vei.world.scenario import Document, Scenario


class DocsSim:
    """Minimal document store twin for deterministic simulations."""

    def __init__(self, scenario: Optional[Scenario] = None):
        base = dict(scenario.documents) if scenario and scenario.documents else {}
        self.docs: Dict[str, Document] = base
        self._doc_seq = self._init_seq()

    def list(self) -> List[Dict[str, object]]:
        return [
            {
                "doc_id": doc.doc_id,
                "title": doc.title,
                "tags": list(doc.tags or []),
            }
            for doc in self.docs.values()
        ]

    def read(self, doc_id: str) -> Dict[str, object]:
        doc = self.docs.get(doc_id)
        if not doc:
            raise ValueError(f"unknown document: {doc_id}")
        return {
            "doc_id": doc.doc_id,
            "title": doc.title,
            "body": doc.body,
            "tags": list(doc.tags or []),
        }

    def create(
        self, title: str, body: str, tags: Optional[List[str]] = None
    ) -> Dict[str, object]:
        doc_id = f"DOC-{self._doc_seq}"
        self._doc_seq += 1
        doc = Document(doc_id=doc_id, title=title, body=body, tags=tags or None)
        self.docs[doc_id] = doc
        return {"doc_id": doc_id, "title": title}

    def update(
        self,
        doc_id: str,
        title: Optional[str] = None,
        body: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, object]:
        doc = self.docs.get(doc_id)
        if not doc:
            raise ValueError(f"unknown document: {doc_id}")
        if title is not None:
            doc.title = title
        if body is not None:
            doc.body = body
        if tags is not None:
            doc.tags = tags or None
        self.docs[doc_id] = doc
        return {"doc_id": doc_id, "title": doc.title}

    def search(self, query: str) -> List[Dict[str, object]]:
        needle = query.lower().strip()
        hits = []
        if not needle:
            return hits
        for doc in self.docs.values():
            if needle in doc.title.lower() or needle in doc.body.lower():
                hits.append({"doc_id": doc.doc_id, "title": doc.title})
        return hits

    def deliver(self, event: Dict[str, object]) -> Dict[str, object]:
        """Apply a scheduled docs event using the same shape as docs tools."""
        payload = dict(event or {})
        op = str(payload.get("op", "")).lower()
        doc_id = payload.get("doc_id")
        if op == "update" or (isinstance(doc_id, str) and doc_id in self.docs):
            if not isinstance(doc_id, str):
                raise ValueError("docs.update delivery requires doc_id")
            return self.update(
                doc_id=doc_id,
                title=(
                    payload.get("title")
                    if isinstance(payload.get("title"), str)
                    else None
                ),
                body=(
                    payload.get("body")
                    if isinstance(payload.get("body"), str)
                    else None
                ),
                tags=(
                    payload.get("tags")
                    if isinstance(payload.get("tags"), list)
                    else None
                ),
            )

        title = payload.get("title")
        body = payload.get("body")
        if not isinstance(title, str) or not isinstance(body, str):
            raise ValueError("docs delivery requires title/body for create")
        tags = payload.get("tags") if isinstance(payload.get("tags"), list) else None
        return self.create(title=title, body=body, tags=tags)

    def _init_seq(self) -> int:
        seq = 1
        for doc_id in self.docs.keys():
            try:
                if doc_id.startswith("DOC-"):
                    seq = max(seq, int(doc_id.split("-", 1)[1]) + 1)
            except ValueError:
                continue
        return seq
