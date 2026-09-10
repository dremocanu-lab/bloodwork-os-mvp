import hashlib

from app.services.file_hash import compute_sha256


def test_compute_sha256_matches_stdlib(tmp_path):
    content = b"synthetic test content, not a real document"
    file_path = tmp_path / "sample.txt"
    file_path.write_bytes(content)

    assert compute_sha256(file_path) == hashlib.sha256(content).hexdigest()


def test_compute_sha256_differs_for_different_content(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_bytes(b"content a")
    b.write_bytes(b"content b")

    assert compute_sha256(a) != compute_sha256(b)


def test_compute_sha256_stable_for_same_content(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_bytes(b"identical content")
    b.write_bytes(b"identical content")

    assert compute_sha256(a) == compute_sha256(b)
