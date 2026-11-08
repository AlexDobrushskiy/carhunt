"""Checks for the outreach skill, phrase bank and role brief templates.

Every `{…}` must be a config placeholder that renders against the example config (plus the persona
keys below), every phrase key must exist in all 7 languages, and nothing private may leak in.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "skills" / "carhunt-outreach" / "SKILL.md"
PHRASES = ROOT / "skills" / "carhunt-outreach" / "phrases.md"
BRIEF = ROOT / "agents" / "roles" / "outreach" / "brief.md"
FILES = [SKILL, PHRASES, BRIEF]

LANGS = ["PT", "ES", "DE", "NL", "FR", "IT", "EN"]
PLACEHOLDER = re.compile(r"\{([^{}\s]*)\}")
VALID_NAME = re.compile(r"^(owner|contact|search)(\.[a-z0-9_]+)+$")
# Brace tokens allowed although they are not config placeholders. Keep empty unless a template
# really needs one; each entry needs a comment saying why.
WHITELIST: set[str] = set()

# Keys the templates use that config.example.yaml doesn't carry yet (integrator adds them to the
# `contact` section). Values = the EV run, generalized.
CONFIG_ADDITIONS = {
    "contact": {
        "variant": "home",
        "persona": {
            "home": "Lisbon, Portugal",
            "family_line": "for myself and my family",
            "travel_line": "since I'd travel to see it, I want everything clear before the trip",
            "health_report": "a recent battery health report (SoH)",
            "spec_line": "Does it have electric seats, a panoramic roof and a heat pump?",
            "payment_line": (
                "I'd pay at handover by instant bank transfer, banker's draft or cash; "
                "no deposit before."
            ),
        },
    }
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


@pytest.fixture(scope="module")
def config() -> dict:
    base = yaml.safe_load((ROOT / "config.example.yaml").read_text())
    return _merge(base, CONFIG_ADDITIONS)


def lookup(cfg: dict, dotted: str):
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(dotted)
        node = node[part]
    if isinstance(node, dict):
        raise KeyError(f"{dotted} is a section, not a value")
    return node


def render(text: str, cfg: dict) -> str:
    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name in WHITELIST:
            return m.group(0)
        value = lookup(cfg, name)
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        return str(value)

    return PLACEHOLDER.sub(sub, text)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_braces_are_valid_placeholders(path: Path) -> None:
    text = path.read_text()
    names = PLACEHOLDER.findall(text)
    bad = [n for n in names if n not in WHITELIST and not VALID_NAME.match(n)]
    assert not bad, f"invalid placeholders in {path.name}: {bad}"
    stray = PLACEHOLDER.sub("", text)
    assert "{" not in stray and "}" not in stray, f"literal brace in {path.name}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_renders_with_sample_config(path: Path, config: dict) -> None:
    out = render(path.read_text(), config)
    assert not [n for n in PLACEHOLDER.findall(out) if n not in WHITELIST]


def _phrase_sections() -> tuple[list[str], dict[str, dict[str, str]]]:
    text = PHRASES.read_text()
    keys_par = next(line for line in text.splitlines() if line.startswith("**Keys**"))
    keys = re.findall(r"`([a-z][a-z-]*)`", keys_par)
    sections: dict[str, dict[str, str]] = {}
    current = None
    for line in text.splitlines():
        if m := re.match(r"^## ([A-Z]{2})\s*$", line):
            current = m.group(1)
            sections[current] = {}
        elif current and (m := re.match(r"^- ([a-z][a-z-]*): (.+)$", line)):
            assert m.group(1) not in sections[current], f"{current}: duplicate key {m.group(1)}"
            sections[current][m.group(1)] = m.group(2)
    return keys, sections


def test_phrases_all_languages_all_keys() -> None:
    keys, sections = _phrase_sections()
    assert len(keys) == len(set(keys)) and len(keys) > 30
    assert list(sections) == LANGS
    for lang, rows in sections.items():
        assert set(rows) == set(keys), (
            f"{lang}: missing {sorted(set(keys) - set(rows))}, extra {sorted(set(rows) - set(keys))}"
        )
        assert all(v.strip() for v in rows.values()), f"{lang}: empty phrase"


def test_skill_frontmatter() -> None:
    text = SKILL.read_text()
    assert text.startswith("---\n")
    meta = yaml.safe_load(text.split("---\n")[1])
    assert meta["name"] == "carhunt-outreach"
    assert len(meta["description"]) > 50
    assert "phrases.md" in text


def test_brief_has_both_variants() -> None:
    text = BRIEF.read_text()
    assert "### If you are the home-market agent" in text
    assert "### If you are the abroad agent" in text
    assert "{contact.variant}" in text


EMAIL = re.compile(r"[\w.+-]+@([\w-]+\.)+[a-z]{2,}", re.I)
PHONE = re.compile(r"\+\d[\d ]{6,}")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_privacy_smoke(path: Path) -> None:
    text = path.read_text()
    emails = [m.group(0) for m in EMAIL.finditer(text) if not m.group(0).endswith("@example.com")]
    assert not emails, emails
    assert not PHONE.search(text), PHONE.search(text).group(0)
    assert "/Users/" not in text and "/home/" not in text
