"""Source Geometry + Clinical Table Intelligence V3 — segment-to-block
alignment tests. Pure, no PDF/DB/API — PageGeometry/BlockGeometry
constructed directly."""

from __future__ import annotations

from app.services.clinical_document.geometry_alignment import align_segment_to_blocks
from app.services.clinical_document.source_geometry import BlockGeometry, NormalizedBBox, PageGeometry


def _block(block_id: str, text: str, y: float = 0.1) -> BlockGeometry:
    return BlockGeometry(block_id=block_id, text=text, bbox=NormalizedBBox(x=0.1, y=y, width=0.5, height=0.03))


def test_confident_single_block_match():
    geometry = PageGeometry(
        page_number=4,
        width=595,
        height=842,
        rotation=0,
        blocks=[
            _block("p4-b00", "Concluzie ecografie abdominala: splenomegalie moderata."),
            _block(
                "p4-b01",
                "Pacienta a fost diagnosticata initial in anul 2018, la varsta de 52 de ani, cu Policitemie vera, "
                "confirmata prin biopsie osteomedulara si mutatia JAK2 V617F pozitiva.",
                y=0.2,
            ),
        ],
    )
    matched = align_segment_to_blocks(
        "Pacienta a fost diagnosticata initial in anul 2018, la varsta de 52 de ani, cu Policitemie vera, "
        "confirmata prin biopsie osteomedulara si mutatia JAK2 V617F pozitiva.",
        geometry,
    )
    assert len(matched) == 1
    assert matched[0].block_id == "p4-b01"


def test_confident_match_tolerates_minor_transcription_whitespace_differences():
    geometry = PageGeometry(
        page_number=2,
        width=595,
        height=842,
        rotation=0,
        blocks=[_block("p2-b00", "La 10.05.2019 s-a efectuat  flebotomie   terapeutica (izovolemica), bine tolerata.")],
    )
    matched = align_segment_to_blocks(
        "La 10.05.2019 s-a efectuat flebotomie terapeutica (izovolemica), bine tolerata.", geometry
    )
    assert len(matched) == 1
    assert matched[0].block_id == "p2-b00"


def test_multi_block_match_when_segment_spans_several_consecutive_blocks():
    geometry = PageGeometry(
        page_number=1,
        width=595,
        height=842,
        rotation=0,
        blocks=[
            _block("p1-b00", "Continuare tratament cu Besremi 150 micrograme subcutanat la doua saptamani.", y=0.3),
            _block(
                "p1-b01",
                "Suplimentare cu Silivit F 1 capsula/zi, Lagosa 1 comprimat x2/zi si Sargenor 1 fiola/zi timp de 4 saptamani.",
                y=0.32,
            ),
        ],
    )
    segment_text = (
        "Continuare tratament cu Besremi 150 micrograme subcutanat la doua saptamani. "
        "Suplimentare cu Silivit F 1 capsula/zi, Lagosa 1 comprimat x2/zi si Sargenor 1 fiola/zi timp de 4 saptamani."
    )
    matched = align_segment_to_blocks(segment_text, geometry)
    assert [b.block_id for b in matched] == ["p1-b00", "p1-b01"]


def test_no_confident_match_returns_empty_never_a_wrong_guess():
    geometry = PageGeometry(
        page_number=3,
        width=595,
        height=842,
        rotation=0,
        blocks=[_block("p3-b00", "Cu totul altceva, fara nicio legatura cu segmentul cautat.")],
    )
    matched = align_segment_to_blocks(
        "La 04.03.2026 s-a efectuat ecografie abdominala care a evidentiat splenomegalie moderata.", geometry
    )
    assert matched == []


def test_scanned_page_with_no_geometry_falls_back_to_empty():
    assert align_segment_to_blocks("orice text", None) == []
    empty_geometry = PageGeometry(page_number=1, width=595, height=842, rotation=0, blocks=[], tables=[])
    assert align_segment_to_blocks("orice text", empty_geometry) == []


def test_empty_segment_text_never_matches_anything():
    geometry = PageGeometry(
        page_number=1, width=595, height=842, rotation=0, blocks=[_block("p1-b00", "Some real text.")]
    )
    assert align_segment_to_blocks("", geometry) == []
    assert align_segment_to_blocks("   ", geometry) == []
