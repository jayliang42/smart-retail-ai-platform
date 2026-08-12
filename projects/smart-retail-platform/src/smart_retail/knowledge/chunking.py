"""Deterministic Markdown chunking with stable citation identifiers."""

from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256

from smart_retail.knowledge.embedding import EmbeddingProvider
from smart_retail.knowledge.models import KnowledgeChunk, KnowledgeSource


@dataclass(frozen=True, slots=True)
class _ChunkDraft:
    section: str
    content: str


def create_knowledge_chunks(
    source: KnowledgeSource,
    embedder: EmbeddingProvider,
    *,
    max_characters: int = 700,
) -> list[KnowledgeChunk]:
    if max_characters < 100:
        raise ValueError("max_characters must be at least 100")
    drafts = _chunk_markdown(source, max_characters=max_characters)
    embeddings = embedder.embed_texts([draft.content for draft in drafts])
    chunks: list[KnowledgeChunk] = []
    for ordinal, (draft, embedding) in enumerate(zip(drafts, embeddings, strict=True)):
        identity = (
            f"{source.source_id}\n{source.source_version}\n{ordinal}\n{draft.content}"
        )
        chunk_id = sha256(identity.encode("utf-8")).hexdigest()[:16]
        chunks.append(
            KnowledgeChunk(
                chunk_id=chunk_id,
                source_id=source.source_id,
                source_version=source.source_version,
                title=source.title,
                section=draft.section,
                ordinal=ordinal,
                content=draft.content,
                embedding=embedding,
            )
        )
    return chunks


def _chunk_markdown(source: KnowledgeSource, *, max_characters: int) -> list[_ChunkDraft]:
    drafts: list[_ChunkDraft] = []
    for section, body in _markdown_sections(source.content, default_title=source.title):
        current: list[str] = []
        current_length = 0
        for paragraph in _bounded_paragraphs(body, max_characters=max_characters):
            added_length = len(paragraph) + (2 if current else 0)
            if current and current_length + added_length > max_characters:
                drafts.append(_ChunkDraft(section=section, content="\n\n".join(current)))
                current = []
                current_length = 0
            current.append(paragraph)
            current_length += len(paragraph) + (2 if len(current) > 1 else 0)
        if current:
            drafts.append(_ChunkDraft(section=section, content="\n\n".join(current)))
    if not drafts:
        raise ValueError("knowledge source produced no chunks")
    return drafts


def _markdown_sections(content: str, *, default_title: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading = default_title
    body_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("#"):
            if any(item.strip() for item in body_lines):
                sections.append((current_heading, "\n".join(body_lines).strip()))
            current_heading = line.lstrip("#").strip() or default_title
            body_lines = []
        else:
            body_lines.append(line)
    if any(item.strip() for item in body_lines):
        sections.append((current_heading, "\n".join(body_lines).strip()))
    return sections


def _bounded_paragraphs(body: str, *, max_characters: int) -> Iterable[str]:
    for paragraph in (item.strip() for item in body.split("\n\n")):
        if not paragraph:
            continue
        if len(paragraph) <= max_characters:
            yield paragraph
            continue

        words = paragraph.split()
        current: list[str] = []
        current_length = 0
        for word in words:
            added_length = len(word) + (1 if current else 0)
            if current and current_length + added_length > max_characters:
                yield " ".join(current)
                current = []
                current_length = 0
            current.append(word)
            current_length += len(word) + (1 if len(current) > 1 else 0)
        if current:
            yield " ".join(current)
