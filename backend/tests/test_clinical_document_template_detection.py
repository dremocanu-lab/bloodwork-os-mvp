"""Clinical Reader Intelligence V2: deterministic empty-template
detection — see app/services/clinical_document/template_detection.py."""

from app.services.clinical_document.canonical_headings import consolidate_segments
from app.services.clinical_document.segments import SourceSegment
from app.services.clinical_document.template_detection import (
    is_template_placeholder_text,
    section_blocks_are_all_template_noise,
)


def test_pure_template_table_is_detected():
    text = "PRODUS\nCANTITATE\nPRODUS\nCANTITATE\nNotă: se completeaza doar daca se elibereaza produse."
    assert is_template_placeholder_text(text) is True


def test_blank_underscore_fields_are_detected():
    text = "DIAGNOSTIC PRINCIPAL (DRG Cod 2):\n________\n\nDIAGNOSTICE SECUNDARE:\n________"
    assert is_template_placeholder_text(text) is True


def test_real_content_is_never_flagged_as_template():
    text = "Silivit F 1 comprimat pe zi, 30 de zile."
    assert is_template_placeholder_text(text) is False


def test_mixed_template_and_real_content_is_not_flagged():
    """One real line among template labels is enough to keep the whole
    text — this function only recognizes the ALL-noise case, never
    partially discards real content."""
    text = "PRODUS\nCANTITATE\nSilivit F — 2 cutii eliberate"
    assert is_template_placeholder_text(text) is False


def test_empty_text_is_not_a_template_it_is_handled_elsewhere():
    assert is_template_placeholder_text("") is False
    assert is_template_placeholder_text(None) is False


def test_section_blocks_all_template_noise():
    assert section_blocks_are_all_template_noise(["PRODUS", "CANTITATE"]) is True
    assert section_blocks_are_all_template_noise(["PRODUS", "Silivit F 1cp/zi"]) is False
    assert section_blocks_are_all_template_noise([]) is False


def test_consolidate_segments_flags_pure_template_section_but_keeps_it():
    segments = [
        SourceSegment(
            segment_id="seg-0",
            index=0,
            segment_type="heading_section",
            raw_heading="TRATAMENT RECOMANDAT",
            raw_text="PRODUS\nCANTITATE\nPRODUS\nCANTITATE",
        ),
    ]
    sections = consolidate_segments(segments, review_state="auto")
    assert len(sections) == 1
    section = sections[0]
    # Never deleted — still present, with its real source text intact —
    # only flagged so the intelligent-reader view can suppress it.
    assert section.is_template_only is True
    assert section.blocks[0].text == "PRODUS\nCANTITATE\nPRODUS\nCANTITATE"


def test_consolidate_segments_does_not_flag_real_treatment_section():
    segments = [
        SourceSegment(
            segment_id="seg-0",
            index=0,
            segment_type="heading_section",
            raw_heading="TRATAMENT RECOMANDAT",
            raw_text="Silivit F 1 comprimat pe zi, 30 de zile.\nLagosa 2 comprimate pe zi.",
        ),
    ]
    sections = consolidate_segments(segments, review_state="auto")
    assert sections[0].is_template_only is False
