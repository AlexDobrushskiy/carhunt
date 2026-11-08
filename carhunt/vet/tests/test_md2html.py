from carhunt.vet import md2html

MD = """# Synthetic report

| Item | Risk |
|---|---|
| 12 V battery | **medium** |

- [ ] check inlet
- recall rule [V], forum claim [A]
"""


def test_convert_pills_cards_checklist(tmp_path):
    out = md2html.convert(MD, cards=True)
    assert "<title>Synthetic report</title>" in out
    assert 'class="res medium"' in out
    assert 'class="tag v"' in out and 'class="tag a"' in out
    assert '<li class="chk">check inlet' in out
    assert 'data-label="Risk"' in out and 'class="cards"' in out
    assert "prefers-color-scheme: dark" in out


def test_main_writes_file(tmp_path):
    src = tmp_path / "r.md"
    src.write_text(MD)
    assert md2html.main([str(src)]) == 0
    assert (tmp_path / "r.html").read_text().startswith("<!doctype html>")
