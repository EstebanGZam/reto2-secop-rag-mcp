"""Parse educational tender PDFs into reproducible, section-aware chunks."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from secop_agent.config import TENDER_DOCS_DIR


@dataclass(frozen=True)
class Chunk:
    """A section fragment with its original source and process identity."""

    chunk_id: str
    text: str
    source_file: str
    page: int
    section: str
    process_id: str
    reference: str
    entity: str
    document_type: str


@dataclass(frozen=True)
class RetrievedChunk:
    """A source chunk and its cosine distance and reranked relevance."""

    chunk: Chunk
    distance: float
    score: float

    def citation(self) -> str:
        """Return the citation syntax consumed by the grounding guard."""
        section = re.sub(r"^(\d+)\.\s*", r"\1 ", self.chunk.section)
        return f"[fuente: {self.chunk.source_file}, p. {self.chunk.page}, §{section}]"


def _clean_page(text: str) -> list[str]:
    """Remove the educational banner and repeated footer without losing content."""
    text = re.sub(
        r"DOCUMENTO SIMULADO CON FINES EDUCATIVOS\..*?ficticios\.",
        "", text, flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(
        r"Documento simulado con fines educativos\s*·[^\n]*", "", text,
        flags=re.IGNORECASE,
    )
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def _split_section(text: str, size: int = 1200, overlap: int = 120) -> list[tuple[int, str]]:
    """Split at whitespace, preserving every character and a small context overlap."""
    if size <= overlap or overlap < 0:
        raise ValueError("Chunk size must exceed non-negative overlap")
    fragments: list[tuple[int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + size // 2, end)
            if boundary != -1:
                end = boundary
        fragments.append((start, text[start:end].strip()))
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
        while 0 < start < end and not text[start - 1].isspace():
            start += 1
    return fragments


def load_tender_document(path: Path) -> list[Chunk]:
    """Extract identity and numbered sections, retaining section/page boundaries."""
    path = Path(path)
    lines = [
        (page_number, line)
        for page_number, page in enumerate(PdfReader(path).pages, start=1)
        for line in _clean_page(page.extract_text(extraction_mode="layout") or "")
    ]
    identity_index = next(
        (i for i, (_, line) in enumerate(lines) if re.match(r"^Proceso .+ · CO1\.REQ\.\d+$", line)),
        None,
    )
    if identity_index is None or identity_index < 2:
        raise ValueError(f"Missing tender identity in {path.name}")
    identity = re.fullmatch(r"Proceso (.+) · (CO1\.REQ\.\d+)", lines[identity_index][1])
    assert identity is not None
    reference, process_id = identity.groups()
    entity = " ".join(line for _, line in lines[:identity_index - 1])
    document_type = lines[identity_index - 1][1]
    sections: list[tuple[str, int, list[tuple[int, str]]]] = []
    for page, line in lines[identity_index + 1:]:
        if re.match(r"^\d{1,2}\.\s+\D", line):
            sections.append((line, page, []))
        elif sections:
            sections[-1][2].append((page, line))
    if not sections:
        raise ValueError(f"No numbered sections found in {path.name}")

    chunks: list[Chunk] = []
    for section, section_page, body in sections:
        prefix = f"{reference} · {entity} · {section}\n"
        content = "\n".join(line for _, line in body)
        page_offsets: list[tuple[int, int]] = []
        offset = 0
        for page, line in body:
            page_offsets.append((offset, page))
            offset += len(line) + 1
        number = int(section.split(".", 1)[0])
        for index, (start, fragment) in enumerate(_split_section(content) or [(0, "")]):
            page = section_page if index == 0 else max(
                (item for item in page_offsets if item[0] <= start), default=(0, section_page),
            )[1]
            chunks.append(Chunk(
                chunk_id=f"{path.name}#s{number:02d}#{index}", text=prefix + fragment,
                source_file=path.name, page=page, section=section,
                process_id=process_id, reference=reference, entity=entity,
                document_type=document_type,
            ))
    return chunks


def load_corpus(directory: Path = TENDER_DOCS_DIR) -> list[Chunk]:
    """Load every PDF in filename order; fail explicitly for a missing corpus."""
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    return [chunk for path in sorted(directory.glob("*.pdf")) for chunk in load_tender_document(path)]
