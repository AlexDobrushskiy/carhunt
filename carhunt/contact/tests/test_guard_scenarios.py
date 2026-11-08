"""The 43 ev-say scenarios (EV run, 2026-11-05) ported to `carhunt say` + the config-driven guard.
End to end via the CLI: fake wacli, cardb stub over HTTP, frozen clock. Nothing is ever sent."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from .conftest import AB_ME, AB_ROLE, ES_NUM, NOW, PT_NUM, car, iso, msg, nudge_tree, sent

N = ["--channel", "whatsapp", "--car", "A9", "--to", PT_NUM, "--text", "Olá, só para confirmar: teve algum acidente?"]
NG = N + ["--nudge"]
EG = ["--channel", "whatsapp", "--car", "77", "--to", ES_NUM, "--text", "Hola, ¿tuvo algún accidente?", "--nudge"]


def ok(res, needle=""):
    code, out = res
    assert code == 0 and needle in out, out


def refused(res, needle):
    code, out = res
    assert code == 10 and needle in out, out


# --- regression: the base guards (10) ---

def test_reply_to_sellers_message(tree):
    tree.chats[PT_NUM] = [msg(NOW - timedelta(minutes=10), False, "Olá")]
    ok(tree.run(*N), "DRY-RUN OK")


def test_seller_message_under_3_min(tree):
    tree.chats[PT_NUM] = [msg(NOW - timedelta(minutes=1), False, "Olá")]
    refused(tree.run(*N), "< 3 min")


def test_double_message_refused(tree):
    refused(nudge_tree(tree).run(*N), "no double messages")


def test_double_message_with_approved(tree):
    ok(nudge_tree(tree).run(*N, "--approved"), "DRY-RUN OK")


def test_opener_on_empty_chat(tree):
    ok(tree.run(*N, "--opener"), "DRY-RUN OK")


def test_opener_on_chat_with_our_message(tree):
    refused(nudge_tree(tree).run(*N, "--opener"), "not an opener")


def test_quiet_hours(tree):
    refused(tree.run(*N, now=datetime(2026, 11, 10, 3, 0, tzinfo=timezone.utc)), "quiet hours")


def test_global_180s_spacing(tree):
    tree.chats[PT_NUM] = [msg(NOW - timedelta(minutes=10), False, "Olá")]
    tree.ledger = [sent(NOW - timedelta(seconds=60), "351555000000", "x")]
    refused(tree.run(*N), "chat-spacing")


def test_caller_not_active_agent(tree):
    refused(tree.run(*N, me="SOMEONE"), "not the active outreach-home agent")


def test_target_closed(tree):
    tree.stub.cars["A9"]["status"] = "dropped"
    refused(tree.run(*N), "target is closed")


# --- --nudge (33) ---

def test_nudge_happy_path(tree):
    ok(nudge_tree(tree).run(*NG), "DRY-RUN OK")


@pytest.mark.parametrize("flag", ["--opener", "--approved"])
def test_nudge_combined_flags(tree, flag):
    refused(nudge_tree(tree).run(*NG, flag), "can't be combined")


def test_nudge_under_48h(tree):
    t = nudge_tree(tree)
    t.chats[PT_NUM][-1]["Timestamp"] = iso(NOW - timedelta(hours=47))
    t.ledger[-1]["t"] = (NOW - timedelta(hours=47)).timestamp()
    refused(t.run(*NG), "< 48 h")


def test_nudge_latest_is_sellers(tree):
    t = nudge_tree(tree)
    t.chats[PT_NUM].append(msg(NOW - timedelta(hours=1), False, "Não teve."))
    refused(t.run(*NG), "reply normally")


def test_nudge_seller_never_replied(tree):
    t = nudge_tree(tree)
    del t.chats[PT_NUM][1]
    refused(t.run(*NG), "never really replied")


def test_nudge_only_auto_reply(tree):
    t = nudge_tree(tree)
    t.chats[PT_NUM][1]["Timestamp"] = iso(NOW - timedelta(days=4) + timedelta(seconds=5))
    refused(t.run(*NG), "never really replied")


def test_nudge_only_reaction(tree):
    t = nudge_tree(tree)
    t.chats[PT_NUM][1].update(Text="", ReactionEmoji="👍")
    refused(t.run(*NG), "never really replied")


def test_nudge_photo_counts_as_reply(tree):
    t = nudge_tree(tree)
    t.chats[PT_NUM][1].update(Text="", MediaType="image")
    ok(t.run(*NG), "DRY-RUN OK")


def test_nudge_second_nudge(tree):
    t = nudge_tree(tree)
    t.ledger.insert(1, sent(NOW - timedelta(days=3), PT_NUM, "Ainda aí?", kind="nudge"))
    refused(t.run(*NG), "already had its one nudge")


def test_nudge_after_owner_approved_send(tree):
    t = nudge_tree(tree)
    t.ledger.insert(1, sent(NOW - timedelta(days=3), PT_NUM, "Proposta", kind="approved"))
    refused(t.run(*NG), "owner approved")


def test_nudge_price_talk(tree):
    t = nudge_tree(tree)
    t.chats[PT_NUM][1]["Text"] = "Sim, está. O preço é negociável."
    refused(t.run(*NG), "price talk")


def test_nudge_seller_said_sold(tree):
    t = nudge_tree(tree)
    t.chats[PT_NUM][1]["Text"] = "Lamento, já foi vendido."
    refused(t.run(*NG), "no/sold")


def test_nudge_owner_wrote_himself(tree):
    t = nudge_tree(tree)
    t.chats[PT_NUM].insert(2, msg(NOW - timedelta(days=3), True, "Olá, falamos amanhã por telefone"))
    refused(t.run(*NG), "the owner wrote")


def test_nudge_not_good(tree):
    t = nudge_tree(tree)
    t.stub.cars["A9"]["tier"] = 2
    refused(t.run(*NG), "isn't really good")


def test_nudge_thumbs_up_only(tree):
    t = nudge_tree(tree)
    t.stub.cars["A9"].update(tier=2, verdict={"value": "up"})
    ok(t.run(*NG), "DRY-RUN OK")


def test_nudge_good_deal_only(tree):
    t = nudge_tree(tree)
    t.stub.cars["A9"].update(tier=2, good_deal=True)
    ok(t.run(*NG), "DRY-RUN OK")


def test_nudge_quiet_family_excluded(tree):
    t = nudge_tree(tree)
    t.stub.cars["A9"].update(tier=2, verdict={"value": "up"}, model_family="Mercedes EQB", power_kw=140)
    refused(t.run(*NG), "exclude rule goes quiet")


def test_nudge_vag_204hp_excluded(tree):
    t = nudge_tree(tree)
    t.stub.cars["A9"].update(tier=2, verdict={"value": "up"}, power_kw=150)
    refused(t.run(*NG), "VAG 204 hp")


def test_nudge_status_not_nudgeable(tree):
    t = nudge_tree(tree)
    t.stub.cars["A9"]["status"] = "visited"
    refused(t.run(*NG), "cardb status visited")


def test_nudge_number_not_on_seller(tree):
    t = nudge_tree(tree)
    t.stub.cars["A9"]["seller"]["contacts"] = [{"kind": "phone", "value": "351555000000"}]
    refused(t.run(*NG), "is not a contact")


def test_nudge_car_missing(tree):
    t = nudge_tree(tree)
    del t.stub.cars["A9"]
    refused(t.run(*NG), "not found in cardb")


def test_nudge_followup_cap_other_channels(tree):
    t = nudge_tree(tree)
    t.ledger += [sent(NOW - timedelta(minutes=120 - i), f"d{i}@example.com", "follow-up", kind="nudge", channel="email")
                 for i in range(15)]
    refused(t.run(*NG), "followups-daily")


def test_nudge_14_followups_failed_and_yesterday_not_counted(tree):
    t = nudge_tree(tree)
    t.ledger += [sent(NOW - timedelta(minutes=120 - i), f"d{i}@example.com", "follow-up", kind="nudge", channel="email")
                 for i in range(14)]
    t.ledger += [sent(NOW - timedelta(minutes=90), "x@example.com", "f", kind="nudge", channel="email", status="failed"),
                 sent(NOW - timedelta(days=1), "y@example.com", "f", kind="nudge", channel="email")]
    ok(t.run(*NG), "DRY-RUN OK")


def test_nudge_followup_cap_whatsapp_nudges(tree):
    t = nudge_tree(tree)
    t.ledger += [sent(NOW - timedelta(minutes=540 - 30 * i), f"3515550000{i:02d}", "x", kind="nudge") for i in range(15)]
    refused(t.run(*NG), "followups-daily")


def test_nudge_saturday_afternoon(tree):
    refused(nudge_tree(tree).run(*NG, now=datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)), "outside 08:30-13:00")


def test_nudge_sunday_early(tree):
    refused(nudge_tree(tree).run(*NG, now=datetime(2026, 11, 15, 9, 30, tzinfo=timezone.utc)), "outside 10:00-19:00")


def test_nudge_sunday_11(tree):
    ok(nudge_tree(tree).run(*NG, now=datetime(2026, 11, 15, 11, 0, tzinfo=timezone.utc)), "DRY-RUN OK")


def _es(tree):
    return nudge_tree(tree, ES_NUM, "77")


def test_nudge_abroad_agent_madrid_noon(tree):
    ok(_es(tree).run(*EG, me=AB_ME, role=AB_ROLE), "DRY-RUN OK")


def test_nudge_abroad_madrid_1910(tree):
    refused(_es(tree).run(*EG, me=AB_ME, role=AB_ROLE, now=datetime(2026, 11, 10, 18, 10, tzinfo=timezone.utc)),
            "outside 08:30-19:00")


def test_nudge_unknown_country_code(tree):
    num = "8613555000000"
    t = nudge_tree(tree, num, "77")
    t.stub.cars["77"] = car(num)
    refused(t.run("--channel", "whatsapp", "--car", "77", "--to", num, "--text", "hi", "--nudge",
                  me=AB_ME, role=AB_ROLE), "no timezone")


def test_nudge_logged_as_nudge(tree):
    t = nudge_tree(tree)
    code, out = t.run(*NG, dry=False)
    assert code == 0, out
    assert t.ledger_rows()[-1]["kind"] == "nudge" and t.wacli_sends()


def test_reply_logged_as_reply(tree):
    tree.chats[PT_NUM] = [msg(NOW - timedelta(minutes=10), False, "Olá")]
    code, out = tree.run(*N, dry=False)
    assert code == 0, out
    row = tree.ledger_rows()[-1]
    assert row["kind"] == "reply" and row["status"] == "sent"
    assert tree.stub.messages[-1]["dedupe_key"] == row["id"]  # logged to cardb at once, key = ledger id
