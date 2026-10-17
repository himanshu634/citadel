"""Splitting text into chunks and hashing it (brain.chunking). Pure: no graph, no model."""

from __future__ import annotations

from brain.chunking import split_text, text_hash


def test_split_packs_paragraphs_and_hard_splits_long_ones():
    text = "a" * 10 + "\n\n" + "b" * 10 + "\n\n" + ("word " * 400)
    parts = split_text(text, max_chars=1200)
    assert parts[0] == "a" * 10 + "\n\n" + "b" * 10
    assert all(len(p) <= 1200 for p in parts) and len(parts) == 3


def test_split_empty_and_hash_stable():
    assert split_text("  \n\n ") == []
    assert split_text("") == []
    assert text_hash("x") == text_hash("x") != text_hash("y") and len(text_hash("x")) == 16


def test_split_keeps_a_short_text_whole_and_strips_it():
    assert split_text("  one paragraph\nwith a line break \n") == [
        "one paragraph\nwith a line break"
    ]


def test_split_hard_cut_without_a_space_still_respects_the_limit():
    parts = split_text("x" * 2500, max_chars=1000)
    assert [len(p) for p in parts] == [1000, 1000, 500]
