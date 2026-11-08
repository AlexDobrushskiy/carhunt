"""CLI: `carhunt vin decode|check-digit|rdw|prcodes`, `carhunt evidence CAR`."""
from __future__ import annotations

import argparse
import json
import sys

from carhunt.vet import evidence_pack, prcodes, rdw, vin


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("vin", help="VIN / plate / PR-code tools (offline unless noted)")
    sub = p.add_subparsers(dest="vin_cmd", required=True)

    d = sub.add_parser("decode", help="WMI, region, model year, check digit, market flags")
    d.add_argument("vin")
    d.add_argument("--reg", help="first registration YYYY[-MM] (model-year consistency check)")
    d.add_argument("--vpic", action="store_true", help="also query NHTSA vPIC (network; NA cars)")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=_decode)

    c = sub.add_parser("check-digit", help="expected position-9 check digit")
    c.add_argument("vin")
    c.set_defaults(func=_check_digit)

    r = sub.add_parser("rdw", help="NL RDW open data by plate (network, free, no key)")
    r.add_argument("plate")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=_rdw)

    pr = sub.add_parser("prcodes", help="decode VW-group PR codes from the sticker")
    pr.add_argument("codes", nargs="+", help="codes or free text, e.g. '3FU 4E7 9M3'")
    pr.add_argument("--brand", default="vag")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=_prcodes)

    e = subparsers.add_parser(
        "evidence", help="evidence-pack state for a car; optional ask events",
        description="Evidence-pack state of one car from cardb; --write-asks queues the next ask(s) for outreach.",
        epilog="exit codes: 0 visit-ready · 4 not visit-ready (missing items / red flags; see the output) · "
               "1 no config, or cardb unreachable / car not found (message on stderr)",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    e.add_argument("car", help="cardb id or alias")
    e.add_argument("--write-asks", action="store_true",
                   help="write the next `ask` event(s) for the outreach agent (vet never messages sellers)")
    e.add_argument("--max-asks", type=int, help="open asks allowed at once (default: vet.max_open_asks or 1)")
    e.add_argument("--json", action="store_true")
    e.set_defaults(func=_evidence)


def _out(obj, as_json: bool, text: str) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2) if as_json else text)


def _decode(a) -> int:
    info = vin.decode(a.vin, first_reg=a.reg)
    d = info.to_dict()
    if a.vpic and info.valid_format:
        try:
            d["vpic"] = vin.vpic(info.vin)
        except Exception as ex:  # network is optional
            d["vpic_error"] = str(ex)
    lines = [f"VIN {info.vin}  format {'ok' if info.valid_format else 'INVALID'}"]
    lines += [f"  error: {e}" for e in info.errors]
    if info.valid_format:
        cd = info.check_digit
        lines += [f"  WMI {info.wmi}: {info.manufacturer or '?'}  ({info.country or '?'}, {info.region or '?'})",
                  f"  model year {info.model_year or '?'} (code {info.vin[9]}; candidates "
                  f"{info.model_year_candidates})  plant code {info.plant_code}",
                  f"  check digit {cd['actual']} expected {cd['expected']} "
                  f"({'ok' if cd['valid'] else 'mismatch'}; {'mandatory' if cd['mandatory'] else 'not used in EU'})"]
    lines += [f"  [{f.severity}] {f.code}: {f.text}" for f in info.flags]
    if "vpic" in d:
        lines += [f"  vpic {k}: {v}" for k, v in d["vpic"].items()]
    _out(d, a.json, "\n".join(lines))
    return 2 if info.red else 0


def _check_digit(a) -> int:
    v = vin.normalize(a.vin)
    try:
        exp = vin.check_digit(v)
    except ValueError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1
    ok = v[8] == exp
    print(f"{exp} ({'matches' if ok else 'position 9 is ' + v[8]})")
    return 0 if ok else 3


def _rdw(a) -> int:
    rep = rdw.lookup(a.plate)
    if a.json:
        _out(rep.to_dict(), True, "")
    else:
        print(rep.fact_value())
        for f in rep.red_flags:
            print(f"  ! {f}")
        if rep.found:
            print(f"  cardb fact CAR rdw=\"{rep.fact_value()}\":vin_decoder")
    return 0 if rep.found else 3


def _prcodes(a) -> int:
    dec, unknown = prcodes.decode(a.codes, a.brand)
    if a.json:
        _out({"decoded": [d.__dict__ for d in dec], "unknown": unknown,
              "cardb_opt_args": prcodes.cardb_args(dec)}, True, "")
        return 0
    for d in dec:
        val = f"{d.option_key}={d.value}" if d.option_key else "(info)"
        print(f"{d.code}  {val:28} {d.meaning} [{d.confidence}]")
    if unknown:
        print("unknown: " + " ".join(unknown) + "  (decode at oemwolf or ask for the dealer printout)")
    args = prcodes.cardb_args(dec)
    if args:
        print("cardb opt CAR " + " ".join(args))
    return 0


def _evidence(a) -> int:
    from carhunt.core import config, db  # needs a running cardb

    try:
        cfg = config.load()
        max_asks = a.max_asks if a.max_asks is not None else int(cfg.get("vet.max_open_asks", 1) or 1)
        client = db.Client.from_config(cfg)
        st = evidence_pack.run(client, a.car, write_asks=a.write_asks, max_asks=max_asks)
    except (config.ConfigError, db.ApiError) as ex:
        print(f"evidence: {ex}", file=sys.stderr)
        return 1
    _out(st.to_dict(), a.json, evidence_pack.render(st)
         + ("" if a.write_asks or not st.asks else "\n(dry: pass --write-asks to queue them)"))
    return 0 if st.visit_ready else 4
