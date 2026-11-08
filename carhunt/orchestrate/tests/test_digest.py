from carhunt.orchestrate import _core, digest, launch, state

QUEUE = [
    {"position": 1, "tier": 1, "price_gap_pct": -6.0, "why": "heat pump, 1 owner",
     "car": {"id": 41, "make": "Skoda", "model": "Enyaq", "year": 2022, "km": 31000, "price_eur": 29900}},
    {"position": 2, "tier": 1, "car": {"id": 7, "make": "Volkswagen", "model": "ID.4", "price_eur": None}},
]


def setup_agents(home, config, fake, dummy_role):
    launch.launch("dummy", backend=fake, config=config)
    state.set_key("dummy", "summary", "3 replies waiting")
    state.add_key("dummy", "pending_owner", {"id": "p1", "question": "Offer on #41?",
                                             "options": [{"key": "A", "text": "29k"}, {"key": "B", "text": "wait"}],
                                             "rec": "A"})
    (home / "agents" / "dummy" / "digest-input.md").write_text("- seller of #7 asked for a call\n")


def test_digest_build(home, config, fake, dummy_role):
    setup_agents(home, config, fake, dummy_role)
    text, buttons = digest.build("morning", backend=fake, config=config, queue=lambda n: QUEUE[:n])
    assert text.startswith("carhunt morning digest · 2026-11-08")
    assert "• dummy: running · ctx 12% · 3 replies waiting" in text
    assert "• #41 Skoda Enyaq 2022 · 31000 km · €29 900 · -6% vs fair · heat pump, 1 owner" in text
    assert "#7 Volkswagen ID.4 · €?" in text
    assert "1. [dummy] Offer on #41?" in text and "A) 29k  B) wait" in text and "→ Rec: A" in text
    assert "• [dummy] seller of #7 asked for a call" in text
    assert buttons == ["1A", "1B"]
    assert launch.unrendered(text) == []


def test_digest_send_consumes_inputs(home, config, fake, dummy_role, monkeypatch):
    setup_agents(home, config, fake, dummy_role)
    sent = []
    monkeypatch.setattr(_core, "notify", lambda text, **kw: sent.append((text, kw)))
    digest.send("evening", backend=fake, config=config, dry_run=True, queue=lambda n: [])
    assert sent == [] and (home / "agents" / "dummy" / "digest-input.md").exists()
    digest.send("evening", backend=fake, config=config, queue=lambda n: [])
    assert sent[0][1]["kind"] == "digest" and "Strong cars\n–" in sent[0][0]
    assert not (home / "agents" / "dummy" / "digest-input.md").exists()
    assert (home / "agents" / "dummy" / "digest-sent" / "2026-11-08-evening.md").exists()


def test_digest_with_no_agents(home, config):
    text, _ = digest.build("morning", backend=None, config=config, queue=lambda n: [])
    assert "Sessions\n–" in text and "Needs you\n–" in text
