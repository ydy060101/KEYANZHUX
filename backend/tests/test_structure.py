"""T2.6: the structure call the reader opens with.

The reader cannot render a page until it knows the page count and the heading
tree, so `/structure` is on the critical path of the first paint. These tests
pin the two properties that keep it cheap and useful:

  * it carries no block text — only the outline, the asset index, the
    references and the metadata, so a 541-page book does not ship 10 748
    blocks before the first page is drawn;
  * the metadata it returns is the metadata the parse stored, anchors
    included (H01), rather than an empty shell.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.models.orm import AssetRow, Document, SectionSummaryRow
from app.models.orm import Block as BlockRow
from app.models.schemas import Anchor, Author, DocMeta
from app.workers import persist

DOC_ID = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"


@pytest.fixture
async def client(session: Any) -> Any:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed(session: Any) -> None:
    session.add(Document(id=DOC_ID, sha256="a" * 64, title="A Paper", status="ready", file_path="x.pdf"))
    anchor = Anchor(doc_id=DOC_ID, block_id="b1_1", page=1, bbox=[0, 0, 10, 10])
    await session.flush()
    session.add_all(
        [
            BlockRow(
                doc_id=DOC_ID, id="b1_1", type="heading", page=1, bbox=[0, 0, 10, 10],
                reading_order=1, section_id="h1", text="1 Introduction",
            ),
            BlockRow(
                doc_id=DOC_ID, id="b1_2", type="paragraph", page=1, bbox=[0, 20, 10, 40],
                reading_order=2, section_id="h1", text="Body text that must not ship with structure.",
            ),
            BlockRow(
                doc_id=DOC_ID, id="b2_1", type="heading", page=2, bbox=[0, 0, 10, 10],
                reading_order=3, section_id="h2", text="2 Method",
            ),
        ]
    )
    session.add(AssetRow(id=f"{DOC_ID}:fig1", doc_id=DOC_ID, kind="figure", page=2, bbox=[0, 0, 5, 5], path="f.png"))
    session.add_all(
        [
            SectionSummaryRow(
                doc_id=DOC_ID, section_id="h1", title="1 Introduction", page=1,
                summary="Body text", block_ids=["b1_2"],
            ),
            SectionSummaryRow(
                doc_id=DOC_ID, section_id="h2", title="2 Method", page=2,
                summary="", block_ids=[],
            ),
        ]
    )
    doc = await session.get(Document, DOC_ID)
    assert doc is not None
    doc.meta = persist.meta_payload(
        DocMeta(
            title="A Paper",
            authors=[Author(name="Ada", affiliation="Lab", anchor=anchor)],
            year=2024,
        )
    )
    await session.commit()


async def test_structure_carries_outline_assets_and_meta(client: Any, session: Any) -> None:
    await _seed(session)
    response = await client.get(f"/api/v1/documents/{DOC_ID}/structure")
    assert response.status_code == 200
    body = response.json()

    assert [item["title"] for item in body["outline"]] == ["1 Introduction", "2 Method"]
    assert body["outline"][1]["page"] == 2
    assert [asset["kind"] for asset in body["assets"]] == ["figure"]
    assert body["assets"][0]["path"].endswith("/assets/fig1")

    meta = body["meta"]
    assert meta["title"] == "A Paper"
    assert meta["authors"][0]["name"] == "Ada"
    assert meta["authors"][0]["anchor"]["block_id"] == "b1_1", "the anchor must survive the round trip (H01)"
    assert meta["year"] == 2024


async def test_structure_ships_no_block_text(client: Any, session: Any) -> None:
    """First paint must not wait on every block of a 541-page book."""
    await _seed(session)
    body = (await client.get(f"/api/v1/documents/{DOC_ID}/structure")).json()
    assert "blocks" not in body
    assert "Body text that must not ship" not in str(body)


async def test_structure_without_stored_meta_still_answers(client: Any, session: Any) -> None:
    """A document parsed before the meta column existed must not 500."""
    session.add(Document(id=DOC_ID, sha256="b" * 64, title="Old", status="ready", file_path="x.pdf"))
    await session.commit()
    body = (await client.get(f"/api/v1/documents/{DOC_ID}/structure")).json()
    assert body["meta"]["title"] == "Old"
    assert body["meta"]["authors"] == []
    assert body["outline"] == []


async def test_outline_lists_sections_not_every_heading_block(client: Any, session: Any) -> None:
    """A heading-typed block inside a section must not become an outline row.

    The 541-page book has 1 014 blocks typed `heading` but 169 sections, so an
    outline built from block types repeats one section id six times on average
    — the reader then renders duplicate React keys and its jump target is
    ambiguous. The outline is the section index's, one row per section.
    """
    await _seed(session)
    session.add(
        BlockRow(
            doc_id=DOC_ID, id="b1_3", type="heading", page=1, bbox=[0, 50, 10, 60],
            reading_order=4, section_id="h1", text="1.1 A numbered line inside the section",
        )
    )
    await session.commit()

    body = (await client.get(f"/api/v1/documents/{DOC_ID}/structure")).json()
    ids = [item["id"] for item in body["outline"]]
    assert ids == ["h1", "h2"], "one row per section, and ids must be unique"
    assert body["outline"][0]["block_id"] == "b1_1", "the jump target is the heading that opened the section"
    assert body["outline"][1]["block_id"] == "b2_1"


async def test_replacing_the_bibliography_is_idempotent(session: Any) -> None:
    """A re-parse writes r1/c1 again; appending would collide (H12).

    The end-of-parse bibliography pass used to add its rows to whatever was
    already stored. Re-parsing a document — a retried job, or a re-upload that
    dedup maps back to the same id — then failed on the citations primary key
    at 97% progress, after ten minutes of parsing.
    """
    from sqlalchemy import func, select

    from app.models.orm import CitationRow, ReferenceRow
    from app.models.schemas import Citation, Reference

    session.add(Document(id=DOC_ID, sha256="c" * 64, title="A Paper", status="parsing", file_path="x.pdf"))
    await session.commit()
    references = [
        Reference(id="r1", index=1, raw="Vaswani et al. 2017.", block_id="b1_1", bbox=[0, 0, 10, 10])
    ]
    citations = [
        Citation(id="c1", marker="[1]", ref_ids=["r1"], block_id="b1_1", bbox=[0, 0, 10, 10], method="regex")
    ]

    for _ in range(2):
        await persist.replace_bibliography(session, DOC_ID, references, citations)
        await session.commit()

    refs = await session.scalar(
        select(func.count()).select_from(ReferenceRow).where(ReferenceRow.doc_id == DOC_ID)
    )
    cites = await session.scalar(
        select(func.count()).select_from(CitationRow).where(CitationRow.doc_id == DOC_ID)
    )
    assert (refs, cites) == (1, 1)


async def test_document_blocks_come_back_in_page_order(session: Any) -> None:
    """Windows each number their blocks from 1, so page must break the tie.

    `load_document_blocks` feeds the end-of-parse bibliography pass. Ordering
    by `reading_order` alone interleaves every window of a long book — the
    book's 1 198 entries came out as 75 — because each window restarts the
    counter at 1.
    """
    session.add(Document(id=DOC_ID, sha256="d" * 64, title="A Book", status="parsing", file_path="x.pdf"))
    # Two windows: page 1 and page 25 both hold blocks numbered from 1.
    session.add_all(
        [
            BlockRow(
                doc_id=DOC_ID, id="b1_1", type="paragraph", page=1, bbox=[0, 0, 10, 10], reading_order=1, text="one"
            ),
            BlockRow(
                doc_id=DOC_ID, id="b1_2", type="paragraph", page=1, bbox=[0, 10, 10, 20], reading_order=2, text="two"
            ),
            BlockRow(
                doc_id=DOC_ID, id="b25_1", type="paragraph", page=25, bbox=[0, 0, 10, 10], reading_order=1, text="three"
            ),
            BlockRow(
                doc_id=DOC_ID, id="b25_2", type="paragraph", page=25, bbox=[0, 10, 10, 20], reading_order=2, text="four"
            ),
        ]
    )
    await session.commit()

    blocks = await persist.load_document_blocks(session, DOC_ID)
    assert [block.text for block in blocks] == ["one", "two", "three", "four"]


async def test_a_legacy_block_id_does_not_invent_a_page(client: Any, session: Any) -> None:
    """`b202` is reading order 202, not page 202 of a 75-page paper.

    Block ids became page-scoped (`b12_3`) in T2.5; documents parsed before
    that carry ids such as `b202`. Deriving the page from the id put 193 of a
    75-page paper's citations on pages that do not exist, so the reader drew
    no marker at all. The page is a column on the block row and is read from
    there.
    """
    from app.models.orm import CitationRow

    session.add(Document(id=DOC_ID, sha256="e" * 64, title="Legacy", status="ready", file_path="x.pdf"))
    # Flush the parent first: the citation's foreign key needs the document
    # row to exist, and SQLAlchemy does not order two pending inserts for us.
    await session.flush()
    session.add(
        BlockRow(doc_id=DOC_ID, id="b202", type="paragraph", page=18, bbox=[0, 0, 10, 10], reading_order=202, text="x")
    )
    session.add(
        CitationRow(
            id=f"{DOC_ID}:c1", doc_id=DOC_ID, marker="[1]", ref_ids=[f"{DOC_ID}:r1"], block_id="b202",
            bbox=[1, 2, 3, 4], method="link_annotation",
        )
    )
    await session.commit()

    body = (await client.get(f"/api/v1/documents/{DOC_ID}/citations")).json()
    assert body[0]["page"] == 18, "the stored page, not the id's number"
