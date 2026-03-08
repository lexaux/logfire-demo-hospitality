from __future__ import annotations

from pathlib import Path

import yaml

from src.schemas import IntegrationDoc


def load_integration_docs(docs_dir: str = "data/docs") -> list[IntegrationDoc]:
    """Load and validate all YAML integration docs."""
    docs = []
    for path in sorted(Path(docs_dir).glob("*.yaml")):
        with open(path) as f:
            raw = yaml.safe_load(f)
        docs.append(IntegrationDoc.model_validate(raw))
    return docs


def build_doc_chunks(docs: list[IntegrationDoc]) -> list[dict]:
    """Flatten integration docs into searchable chunks."""
    chunks = []
    for doc in docs:
        for category, label in [
            ("supported", "Supported"),
            ("partial", "Partial / Quirks"),
            ("not_supported", "Not Supported"),
            ("known_bugs", "Known Bugs"),
        ]:
            sections = getattr(doc, category)
            for section in sections:
                content = "\n".join(f"- {item}" for item in section.items)
                chunks.append(
                    {
                        "system": doc.system,
                        "display_name": doc.display_name,
                        "category": label,
                        "section_title": section.title,
                        "content": content,
                        "search_text": (
                            f"{doc.system} {doc.display_name} {label} {section.title} {content}"
                        ).lower(),
                    }
                )
    return chunks


def search_chunks(
    chunks: list[dict], query: str, systems: list[str] | None = None, top_k: int = 3
) -> list[dict]:
    """Keyword-based search over doc chunks."""
    query_terms = set(query.lower().split())

    scored = []
    for chunk in chunks:
        if systems and chunk["system"] not in systems:
            continue
        search_text = chunk["search_text"]
        matches = sum(1 for term in query_terms if term in search_text)
        if matches > 0:
            score = matches / len(query_terms) if query_terms else 0
            scored.append({**chunk, "relevance_score": round(score, 2)})

    scored.sort(key=lambda x: x["relevance_score"], reverse=True)
    return scored[:top_k]
