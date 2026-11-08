"""config.example.yaml and config.schema.json stay in step with what the code reads.

(a) the example validates; (b) cardb's Go profile loader takes it with no warnings; (c) every key path the code,
brief templates or skills read is declared in the schema, and module defaults validate against it.
"""
import dataclasses
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from carhunt.core import config

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "config.example.yaml"

# Key paths read outside cardb's Go loader (which parses owner/search/cardb itself; (b) covers it).
# `*` = free-form map key, `[]` = list item. Keep sorted by section; add a line when code reads a new key.
READ_KEYS = """
owner.name owner.languages owner.tz owner.home.city owner.home.country owner.home.lat owner.home.lon
secrets.backend secrets.keychain_service secrets.op_vault
notify.backend notify.telegram.bot_token notify.telegram.chat_id notify.telegram.api_base notify.quiet_hours
notify.quiet.digest notify.quiet.ask notify.quiet.urgent notify.default_agent
cardb.url cardb.token cardb.data_dir cardb.users.[].name cardb.users.[].role
search.countries search.exclude_regions search.price.max_eur search.price.min_eur search.year_min search.km_max
search.powertrain search.private_sellers_abroad search.max_distance_km search.road_factor
search.models.[].make search.models.[].model search.models.[].tier search.models.[].match
search.hard_filters.[].flag search.hard_filters.[].fact search.hard_filters.[].field search.hard_filters.[].min
search.hard_filters.[].max search.options_wanted.*
browsers.chrome_app browsers.lanes browsers.identity_pool browsers.launchd_prefix browsers.mcp_name_prefix
browsers.idle_release_s browsers.reaper_max_age_h browsers.headless browsers.identity_reseed_hours
browsers.ports.mcp_base browsers.ports.debug_base browsers.ports.plain_debug
net.proxy.provider net.proxy.credentials net.proxy.gateway net.proxy.echo_url net.geo.*.tz net.geo.*.locale
accounts.email accounts.sms.provider accounts.sms.api_key accounts.gmail.oauth_client accounts.gmail.token
accounts.gmail.plus_address
sites.enabled sites.overrides.*.country_ip sites.overrides.*.route sites.overrides.*.tab_home
sites.overrides.*.accept_language sites.overrides.*.proxy.sticky_minutes
sites.overrides.*.pace.min_gap_s sites.overrides.*.pace.max_loads_per_run sites.overrides.*.pace.max_loads_per_hour
sites.overrides.*.pace.max_loads_per_day sites.overrides.*.pace.fresh_profile_every
sites.overrides.*.pace.api_min_gap_s sites.overrides.*.pace.max_api_per_hour
sites.overrides.*.liveness.supported sites.overrides.*.liveness.mode sites.overrides.*.liveness.gone_redirect
sites.overrides.*.liveness.gone_text sites.overrides.*.liveness.gone_title sites.overrides.*.liveness.sold_text
sites.overrides.*.liveness.proxy_country sites.overrides.*.account.verification sites.overrides.*.account.mail_from
sites.overrides.*.account.note
sites.overrides.*.caps.load_per_day sites.overrides.*.caps.api_per_day sites.overrides.*.caps.phone_per_day
sites.overrides.*.caps.phone_per_session sites.overrides.*.caps.send_per_day sites.overrides.*.caps.login_per_day
sites.overrides.*.caps.phone_per_hour sites.overrides.*.caps.send_min_gap_s
sites.overrides.*.geo
discover.windows.* discover.max_loads_per_site discover.max_pages discover.detail_tiers discover.max_photos
discover.cursor.* discover.price_sanity.max_eur discover.thin.min_photos
discover.thin.min_info discover.heuristics discover.distance.geocoder discover.distance.router
discover.distance.user_agent
contact.variant contact.quiet_hours contact.opener_window contact.seller_hours.*.* contact.blocked_statuses
contact.duplicate_prefix contact.allow_unlisted contact.require_active_agent
contact.limits.[].name contact.limits.[].channels contact.limits.[].kind contact.limits.[].per_channel
contact.limits.[].min_gap_s contact.limits.[].per contact.limits.[].max contact.limits.[].reserve.role
contact.limits.[].reserve.slots contact.limits.[].reserve.until
contact.reply.min_seller_age_s contact.reply.owner_backoff_min
contact.opener.max_chars contact.opener.max_questions contact.opener.spec_pattern
contact.nudge.after_h contact.nudge.auto_reply_s contact.nudge.statuses contact.nudge.qualify contact.nudge.exclude
contact.nudge.seller_hours contact.nudge.price_extra contact.nudge.no_extra
contact.channels.*.max_len contact.channels.*.seller_hours contact.phone_tz.* contact.country_tz.*
contact.default_phone_cc contact.whatsapp.wacli contact.whatsapp.account
contact.email.from_address contact.email.from_name contact.email.plus_tag contact.email.label
contact.email.sent_label contact.email.verify_tries contact.email.verify_wait_s contact.email.poll_overlap_s
contact.email.poll_ignore contact.email.poll_limit contact.email.oauth_client contact.email.token
contact.mailroute.domains contact.mailroute.never_touch contact.mailroute.freemail contact.mailroute.addresses
contact.mailroute.deep_at contact.watch.channels contact.persona.aliases contact.persona.*
contact.sites.*.selectors.box contact.sites.*.selectors.persona_fields
vet.destination_country vet.max_open_asks
orchestrate.session_backend orchestrate.mailbox orchestrate.workspace orchestrate.agent_cli
orchestrate.agent_args.claude orchestrate.agent_args.codex orchestrate.handover_ctx_pct orchestrate.cycle_minutes
orchestrate.digest_strong_cars orchestrate.schedule.* orchestrate.schedule_commands.*
orchestrate.hooks.secret_globs orchestrate.hooks.send_patterns.[].regex orchestrate.hooks.send_patterns.[].use
""".split()

# `{section.key}` placeholders in role briefs/skills that are not config (filled by `agent launch`).
TEMPLATE_NON_CONFIG = {"agent", "learned", "task", "dotted", "car", "vin", "country", "destination", "tasks",
                       "options", "stage", "carhunt_home", "agent_dir"}


def _ref(root: dict, node: dict) -> dict:
    while "$ref" in node:
        node = root["$defs"][node["$ref"].rsplit("/", 1)[1]]
    return node


def _find(root: dict, node: dict, segs: list[str]) -> bool:
    node = _ref(root, node)
    if not segs:
        return True
    branches = node.get("oneOf", []) + node.get("anyOf", [])
    if any(_find(root, b, segs) for b in branches if "$ref" in b or "properties" in b or "items" in b
           or "additionalProperties" in b):
        return True
    seg, rest = segs[0], segs[1:]
    if seg == "[]":
        return isinstance(node.get("items"), dict) and _find(root, node["items"], rest)
    if seg == "*":
        return isinstance(node.get("additionalProperties"), dict) and _find(root, node["additionalProperties"], rest)
    child = node.get("properties", {}).get(seg)
    if child is None:
        child = next((v for rx, v in node.get("patternProperties", {}).items() if re.search(rx, seg)), None)
    if child is None and isinstance(node.get("additionalProperties"), dict):
        child = node["additionalProperties"]  # a concrete key of a free-form map (discover.windows.morning)
    return child is not None and _find(root, child, rest)


def declared(path: str) -> bool:
    root = config.schema()
    return _find(root, root, path.split("."))


def test_example_validates():
    assert config.validate(config.read(EXAMPLE)) == []


def test_example_has_every_top_level_section():
    assert set(config.read(EXAMPLE)) == set(config.schema()["properties"])


@pytest.mark.parametrize("path", READ_KEYS)
def test_key_read_by_code_is_in_schema(path):
    assert declared(path), f"{path} is read by code but missing from carhunt/core/config.schema.json"


def test_template_placeholders_are_in_schema():
    """Role briefs and skills render `{section.key}` from the config; launch fails on an unknown one."""
    found = set()
    for d in ("agents", "skills"):
        for f in (REPO / d).rglob("*.md"):
            found |= set(re.findall(r"\{([a-z_]+(?:\.[a-z_0-9]+)+)\}", f.read_text()))
    keys = {k for k in found if k.split(".")[0] not in TEMPLATE_NON_CONFIG}
    assert keys, "no placeholders found: template location moved?"
    assert sorted(k for k in keys if not declared(k)) == []
    example = config.Config(config.read(EXAMPLE))
    assert sorted(k for k in keys if example.get(k) is None) == [], "example must set what briefs render"


def test_module_defaults_fit_the_schema():
    """Defaults a module ships must be valid config, so a user can copy any of them."""
    from carhunt.access import settings
    from carhunt.access.captcha.config import CaptchaConfig
    from carhunt.contact.settings import DEFAULTS as CONTACT
    from carhunt.orchestrate.settings import DEFAULTS as ORCH

    browsers = {}
    for f in dataclasses.fields(settings.Settings):
        v = f.default if f.default is not dataclasses.MISSING else f.default_factory()
        if f.name.endswith("_port"):
            browsers.setdefault("ports", {})[f.name.removesuffix("_port")] = v
        else:
            browsers[f.name] = str(v) if isinstance(v, Path) else v
    browsers["captcha"] = dataclasses.asdict(CaptchaConfig())

    orch = {k: dict(v) for k, v in ORCH.items()}
    orch["notify"].pop("digests", None)  # dead key (nothing reads it; schedule.digest does the job)
    data = {**orch, "owner": {**orch["owner"], "tz": "UTC"}, "contact": {**orch["contact"], **CONTACT},
            "browsers": browsers}
    assert config.validate(data) == []


def _cardb_bin(tmp_path_factory) -> str | None:
    if b := os.environ.get("CARDB_BIN") or shutil.which("cardb"):
        return b
    if not shutil.which("go"):
        return None
    out = tmp_path_factory.mktemp("cardb") / "cardb"
    subprocess.run(["go", "build", "-o", str(out), "./cmd/cardb"], cwd=REPO / "cardb", check=True,
                   capture_output=True, timeout=300)
    return str(out)


@pytest.fixture(scope="module")
def cardb_bin(tmp_path_factory):
    b = _cardb_bin(tmp_path_factory)
    if not b:
        pytest.skip("no cardb binary and no Go toolchain (set CARDB_BIN)")
    return b


def test_cardb_profile_loader_takes_example_without_warnings(cardb_bin, tmp_path):
    """`cardb serve` loads + validates the profile first; with no tokens it then stops before opening a DB."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CARDB_", "CARHUNT_"))}
    env["CARHUNT_HOME"] = str(tmp_path)
    r = subprocess.run([cardb_bin, "serve", "-config", str(EXAMPLE), "-data", str(tmp_path / "data"),
                        "-listen", "127.0.0.1:0"], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0 and "no API tokens" in r.stderr, r.stderr  # got past the profile
    assert "msg=profile" not in r.stderr, r.stderr                      # no unknown-key / option warnings
    assert not (tmp_path / "data").exists()
