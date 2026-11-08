#!/usr/bin/env python3
"""Demo stack for README screenshots: cardb on a temp dir + carhunt web, synthetic seed with CC photos.

Usage: demo_stack.py <repo> <photos_dir>   (runs until killed; prints URLs)
"""
import json, os, re, secrets, shutil, signal, subprocess, sys, time, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
PHOTOS = Path(sys.argv[2]).resolve()
BASE = Path(os.environ.get("SCREENS_DIR", "/private/tmp/carhunt-screens")) / "stack"
CARDB_BIN = os.environ.get("CARDB_BIN", "/private/tmp/carhunt-screens/cardb")
DB_PORT, WEB_PORT = 18484, 14321
OWNER, VIEWER = "Sam", "Kim"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat().replace("+00:00", "Z")


def config() -> str:
    src = (REPO / "config.example.yaml").read_text()
    src = src.replace("  name: owner ", f"  name: {OWNER} ", 1)
    src = src.replace("  # users:", "  users:", 1).replace("  #   - {name: partner, role: viewer}", f"    - {{name: {VIEWER}, role: viewer}}", 1)
    src = re.sub(r"\n  hard_filters:.*?\n  options_wanted:", "\n  options_wanted:", src, flags=re.S)
    return src


TOK = {OWNER: secrets.token_hex(18), VIEWER: secrets.token_hex(18), "seed": secrets.token_hex(18)}
API = f"http://127.0.0.1:{DB_PORT}/api/v1"


def call(method, path, body=None, token=TOK["seed"]):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            t = r.read()
            return json.loads(t) if t else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"seed {method} {path}: {e.code} {e.read().decode()[:300]}")


def photo(car, file, caption):
    boundary = secrets.token_hex(8)
    blob = (PHOTOS / file).read_bytes()
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="source"\r\n\r\nad\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode() + blob + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    req = urllib.request.Request(f"{API}/cars/{car}/photos", data=b"".join(parts), method="POST",
                                 headers={"Authorization": f"Bearer {TOK['seed']}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
    urllib.request.urlopen(req).read()


def wait(url, proc, what):
    for _ in range(300):
        if proc.poll() is not None:
            raise SystemExit(f"{what} exited {proc.returncode}")
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except Exception:
            time.sleep(0.2)
    raise SystemExit(f"{what} not up")


n = 0


def car(make, model, variant, reg, km, kw, price, country, city, dist, fuel="bev", net=77, gross=82, rng=None, drive="rwd",
        seller=("private", None), status="new", options=None, facts=None, photos=(), colour=None, interior=None, wheels=None,
        summary=None, site="autoscout24", more_sites=(), price_history=(), **extra):
    global n
    n += 1
    body = {
        "url": f"https://example.invalid/{site}/ad-{n:04d}", "site": site, "make": make, "model": model, "variant": variant,
        "reg_date": reg, "km": km, "power_kw": kw, "drive": drive, "country": country, "city": city,
        "powertrain": {"fuel": fuel, "battery_net_kwh": net, "battery_gross_kwh": gross, "wltp_range_km": rng, "gearbox": "automatic"},
        "vin": f"SYNDEMO{n:010d}", "price": price_history[0] if price_history else price, "price_vat": "gross",
        "seller": {"type": seller[0], "name": seller[1] or ("Private seller" if seller[0] == "private" else "Demo Motors"),
                   "city": city, "contacts": [{"kind": "phone", "value": f"+351 555 {n:03d} {n * 7 % 1000:03d}"}]},
    }
    if dist is not None:
        body["distance_km"] = dist
    for k, v in (("colour", colour), ("interior", interior), ("wheels_in", wheels), ("summary", summary), ("status", status)):
        if v:
            body[k] = v
    body["options"] = {k: {"value": v[0], "source": v[1]} for k, v in (options or {}).items()}
    body["facts"] = {k: {"value": v[0], "source": v[1]} for k, v in (facts or {}).items()}
    body.update(extra)
    cid = call("POST", "/listings/upsert", body)["car_id"]
    for p in price_history[1:] + ((price,) if price_history else ()):
        call("POST", "/listings/upsert", {"url": body["url"], "price": p, "price_vat": "gross"})
    for i, s in enumerate(more_sites):
        call("POST", "/listings/upsert", {"url": f"https://example.invalid/{s}/ad-{n:04d}-{i}", "site": s, "vin": body["vin"],
                                          "make": make, "model": model, "price": price + 400, "price_vat": "gross"})
    for f, cap in photos:
        photo(cid, f, cap)
    return cid


Y, N, U = "yes", "no", "unknown"
KEYMAP = {"vw-id4-a": "id4a", "vw-id4-b": "id4b", "skoda-enyaq-a": "enyaqa", "skoda-enyaq-b": "enyaqb", "audi-q4-etron-a": "q4a",
          "bmw-ix1-a": "ix1", "toyota-bz4x-a": "bz4x", "hyundai-ioniq5-a": "ioniq5a", "kia-ev6-a": "ev6", "tesla-model-y-a": "modely",
          "audi-q4-sportback-etron-a": "q4sb", "kia-niro-ev-a": "niro", "ford-mustang-mach-e-a": "mache", "mercedes-eqa-a": "eqa",
          "volvo-xc40-recharge-a": "xc40"}
SKIP = {"hyundai-ioniq5-a-3.jpg"}  # people visible through the windshield


def seed(ph):
    """ph: model key → list of (file, view)."""
    def P(key, k=4):
        return [(f, v) for f, v in ph.get(key, [])][:k]

    ids = {}
    # peers without photos (pricing pool; below the fold)
    peers = [
        ("Volkswagen", "ID.4", "Pro 77 kWh", "2022-02", 52000, 128, 30900, "ES", "Sevilla", 560),
        ("Volkswagen", "ID.4", "Pro Performance", "2022-10", 29000, 150, 32800, "DE", "Berlin", 2900),
        ("Volkswagen", "ID.4", "GTX", "2022-04", 47000, 220, 33900, "FR", "Lyon", 1700),
        ("Volkswagen", "ID.4", "Pro 77 kWh", "2021-09", 68000, 128, 29400, "PT", "Viseu", 290),
        ("Skoda", "Enyaq", "iV 80", "2022-06", 39000, 150, 31900, "DE", "Stuttgart", 2350),
        ("Skoda", "Enyaq", "iV 80x", "2022-01", 55000, 195, 32500, "BE", "Antwerpen", 2000),
        ("Audi", "Q4 e-tron", "40", "2022-03", 44000, 150, 33400, "DE", "Frankfurt", 2250),
        ("Audi", "Q4 e-tron", "40 Advanced", "2021-07", 66000, 150, 29900, "ES", "Valencia", 900),
        ("BMW", "iX1", "eDrive20", "2023-09", 15000, 150, 38900, "NL", "Eindhoven", 2050),
        ("BMW", "iX1", "xDrive30", "2023-01", 31000, 230, 37500, "FR", "Nantes", 1300),
        ("Toyota", "bZ4X", "Style", "2022-11", 30000, 150, 30900, "PT", "Aveiro", 255),
        ("Toyota", "bZ4X", "Advance AWD", "2023-03", 24000, 160, 34900, "DE", "Köln", 2050),
    ]
    for make, model, var, reg, k, kw, pr, c, city, d in peers:
        car(make, model, var, reg, k, kw, pr, c, city, d, seller=("dealer", None), options={"heat_pump": (U, "ad_spec")})
    # --- the hero car: ID.4 in talks, rich detail ---
    ids["hero"] = car("Volkswagen", "ID.4", "Pro Performance 77 kWh", "2022-06", 38400, 150, 29900, "PT", "Coimbra", 205,
        rng=520, seller=("dealer", "Demo Motors Coimbra"), status="talking", colour="Moonstone grey", interior="black cloth (dark)",
        wheels=20, site="standvirtual", more_sites=("olx", "autoscout24"), price_history=(32900, 31400),
        options={"heat_pump": (Y, "vin_pr_code"), "pano": (Y, "ad_spec"), "camera_360": (N, "vin_pr_code"), "heated_seats": (Y, "ad_spec"),
                 "power_tailgate": (Y, "vin_pr_code"), "adaptive_cruise": (Y, "ad_spec"), "matrix_led": (Y, "photo"), "towbar": (U, "ad_spec")},
        facts={"battery_soh": ("94 % (dealer BMS report)", "seller_said"), "history_report": ("1 owner, PT-registered from new, no accidents", "vin_decoder"),
               "service": ("serviced at 30 000 km, main dealer", "seller_said"), "warranty": ("battery 8 y / 160 000 km to 2030-06", "agent_inference")},
        summary="Heat pump confirmed by PR code, 1 owner, 3 ads → negotiating below 29 k", photos=P("id4a"), seats=5, body="SUV, 5 seats")
    # --- more ID.4 / Enyaq / Q4 / iX1 / bZ4X peers ---
    ids["enyaq"] = car("Skoda", "Enyaq", "iV 80 Loft", "2022-03", 41000, 150, 30500, "ES", "Valladolid", 690, rng=534,
        seller=("dealer", "Demo Cars Valladolid"), status="contacted",
        options={"heat_pump": (Y, "ad_spec"), "pano": (Y, "ad_spec"), "camera_360": (Y, "ad_spec"), "heated_seats": (Y, "ad_spec"), "power_tailgate": (Y, "ad_spec")},
        facts={"battery_soh": ("not given, asked", "agent_inference")}, colour="Velvet red", summary="Full spec; dealer answers within a day",
        photos=P("enyaqa"), site="coches.net")
    ids["ioniq"] = car("Hyundai", "Ioniq 5", "77 kWh Vanguard", "2022-09", 33000, 168, 33900, "DE", "Köln", 1990, rng=481,
        seller=("dealer", "Demo Autohaus"), options={"heat_pump": (Y, "ad_spec"), "pano": (N, "ad_spec"), "camera_360": (Y, "ad_spec")},
        summary="Outside the model list (tier 4); 800 V charging", photos=P("ioniq5a"), site="mobile.de", colour="Phantom black")
    ids["q4"] = car("Audi", "Q4 e-tron", "40 S line", "2021-11", 52000, 150, 31800, "FR", "Bordeaux", 1150, rng=520,
        seller=("dealer", "Demo Auto Bordeaux"), options={"heat_pump": (U, "ad_spec"), "pano": (Y, "photo"), "camera_360": (Y, "ad_spec")},
        photos=P("q4a", 2), site="leboncoin", summary="Heat pump unknown: PR codes requested")
    ids["id4b"] = car("Volkswagen", "ID.4", "Pure 52 kWh", "2021-08", 61000, 109, 22400, "PT", "Porto", 310, net=52, gross=55, rng=345,
        seller=("private", None), status="dropped", options={"heat_pump": (N, "vin_pr_code")}, photos=P("id4b", 2),
        summary="Small battery, no heat pump", site="olx")
    ids["enyaqb"] = car("Skoda", "Enyaq", "iV 60", "2021-10", 48000, 132, 26900, "PT", "Leiria", 140, net=58, gross=62, rng=412,
        seller=("dealer", "Demo Stand Leiria"), status="to_contact", options={"heat_pump": (Y, "ad_spec"), "pano": (N, "ad_spec")},
        photos=P("enyaqb", 2), site="standvirtual", summary="Close to home, fair price; 58 kWh")
    ids["ix1"] = car("BMW", "iX1", "xDrive30", "2023-04", 22000, 230, 39500, "DE", "München", 2400, net=65, gross=67, rng=430, drive="awd",
        seller=("dealer", "Demo Autohaus Süd"), options={"heat_pump": (Y, "ad_spec"), "pano": (Y, "ad_spec"), "camera_360": (N, "ad_spec")},
        photos=P("ix1"), site="mobile.de")
    ids["bz4x"] = car("Toyota", "bZ4X", "Advance", "2023-02", 18000, 150, 32500, "ES", "Madrid", 620, net=64, gross=71, rng=500, drive="fwd",
        seller=("dealer", "Demo Toyota Partner"), options={"heat_pump": (Y, "ad_spec")}, photos=P("bz4x"), site="coches.net")
    ids["ev6"] = car("Kia", "EV6", "GT-Line 77 kWh", "2022-05", 45000, 168, 31200, "NL", "Utrecht", 2150, rng=528,
        seller=("dealer", "Demo Auto NL"), options={"heat_pump": (Y, "ad_spec")}, photos=P("ev6"), site="marktplaats")
    ids["q4sb"] = car("Audi", "Q4 Sportback e-tron", "45 quattro", "2022-07", 35000, 195, 36900, "BE", "Gent", 1900, drive="awd",
        seller=("dealer", "Demo Motors BE"), options={"heat_pump": (Y, "ad_spec"), "pano": (Y, "ad_spec")}, photos=P("q4sb"), site="autoscout24")
    ids["mach"] = car("Ford", "Mustang Mach-E", "Extended Range RWD", "2021-12", 58000, 216, 28900, "DE", "Hamburg", 2600, net=88, gross=99,
        seller=("dealer", "Demo Autohaus Nord"), options={"heat_pump": (Y, "ad_spec")}, photos=P("mache"), site="mobile.de")
    ids["modely"] = car("Tesla", "Model Y", "Long Range AWD", "2022-02", 64000, 378, 29500, "ES", "Barcelona", 1250, net=75, gross=79, drive="awd",
        seller=("private", None), options={"heat_pump": (Y, "vin_decoder"), "pano": (Y, "ad_spec")}, photos=P("modely"), site="wallapop")
    ids["xc40"] = car("Volvo", "XC40 Recharge", "Twin Ultimate", "2021-06", 67000, 300, 30900, "PT", "Lisboa", 15, net=75, gross=78, drive="awd",
        seller=("dealer", "Demo Motors Lisboa"), options={"heat_pump": (Y, "ad_spec"), "pano": (Y, "ad_spec")}, photos=P("xc40"), site="standvirtual")
    ids["niro"] = car("Kia", "Niro EV", "Drive", "2023-01", 26000, 150, 27900, "FR", "Toulouse", 1050, net=64, gross=68, drive="fwd",
        seller=("dealer", "Demo Auto Toulouse"), photos=P("niro"), site="leboncoin")
    ids["eqa"] = car("Mercedes-Benz", "EQA", "250 AMG Line", "2022-01", 39000, 140, 30400, "IT", "Milano", 1850, net=66, gross=70, drive="fwd",
        seller=("dealer", "Demo Auto Milano"), photos=P("eqa"), site="subito")
    return ids


def story(ids):
    h = ids["hero"]
    call("PUT", f"/cars/{ids['enyaqb']}/good-deal", {"good_deal": True, "note": "home market, 2 h away", "author": "learning"})
    msgs = [
        ("out", "agent", "outreach-home", 30, "Bom dia! Vi o vosso ID.4 Pro Performance no StandVirtual. Ainda está disponível? Tem relatório de bateria (SoH) e o histórico de manutenção?"),
        ("in", "seller", "Demo Motors Coimbra", 29, "Bom dia, sim está disponível. O SoH é 94 %, temos o relatório da marca. Revisão feita aos 30 mil km."),
        ("out", "agent", "outreach-home", 28, "Obrigado! Pode enviar o relatório e confirmar se tem bomba de calor? Pelo VIN parece que sim."),
        ("in", "seller", "Demo Motors Coimbra", 26, "Tem bomba de calor sim. Envio o relatório em PDF já a seguir."),
        ("out", "agent", "outreach-home", 6, "Recebido, obrigado. Seria possível 28 900 € com a garantia de 12 meses? Podemos passar para ver na sexta-feira."),
        ("in", "seller", "Demo Motors Coimbra", 2, "Consigo 29 300 € com garantia. Sexta às 15h serve?"),
    ]
    for d, kind, who, hrs, text in msgs:
        call("POST", "/messages", {"car": str(h), "channel": "whatsapp", "direction": d, "sender_kind": kind, "sender": who,
                                   "counterpart": "+351 555 001 007", "text": text, "at": ago(hours=hrs), "delivery": "sent" if d == "out" else "received",
                                   "dedupe_key": f"demo-{hrs}"})
    call("POST", f"/cars/{h}/events", {"type": "vin_check", "summary": "PR codes decoded: heat pump (9M3 + KK2), pano roof, power tailgate", "at": ago(hours=27), "author": "vet"})
    call("POST", f"/cars/{h}/events", {"type": "report", "summary": "History report: 1 owner, no accidents, km plausible", "at": ago(hours=25), "author": "vet"})
    call("POST", f"/cars/{h}/notes", {"text": "Seller flexible on price; ask for winter tyres in the deal.", "pinned": True, "author": "outreach-home", "at": ago(hours=5)})
    call("POST", f"/cars/{h}/notes", {"text": "Check the charge port flap on the visit — common ID.4 wear item.", "author": "vet", "at": ago(hours=20)})
    call("PATCH", f"/cars/{h}", {"needs_owner": True, "needs_owner_reason": "Viewing Fri 15:00 at 29 300 € — OK?"})
    call("PUT", f"/cars/{h}/good-deal", {"good_deal": True, "note": "under fair landed price, 1 owner, heat pump confirmed", "author": "learning"})
    call("PUT", f"/cars/{h}/verdict", {"value": "up", "user": OWNER, "note": "Best so far", "at": ago(hours=24)})
    call("PUT", f"/cars/{h}/verdict", {"value": "up", "user": VIEWER, "at": ago(hours=22)})
    call("PUT", f"/cars/{ids['enyaq']}/verdict", {"value": "maybe", "user": OWNER, "note": "nice spec, far away"})
    call("PUT", f"/cars/{ids['id4b']}/verdict", {"value": "down", "user": OWNER, "note": "52 kWh too small"})
    call("PUT", f"/cars/{ids['xc40']}/verdict", {"value": "maybe", "user": VIEWER})
    call("POST", "/messages", {"car": str(ids["enyaq"]), "channel": "email", "direction": "out", "sender_kind": "agent", "sender": "outreach-abroad",
                               "text": "Hola, ¿sigue disponible el Enyaq iV 80? ¿Tienen el informe de batería?", "at": ago(hours=9), "delivery": "sent", "dedupe_key": "demo-e1"})
    call("POST", f"/cars/{h}/events", {"type": "visit", "summary": "Viewing proposed: Fri 15:00 at the dealer (needs owner OK)", "author": "outreach-home"})


def main():
    if BASE.exists():
        shutil.rmtree(BASE)
    BASE.mkdir(parents=True)
    (BASE / "config.yaml").write_text(config())
    (BASE / "tokens.json").write_text(json.dumps(TOK))
    env = {"PATH": os.environ["PATH"], "HOME": str(BASE), "CARHUNT_HOME": str(BASE), "CARHUNT_CONFIG": str(BASE / "config.yaml"),
           "CARDB_DATA_DIR": str(BASE / "data"), "CARDB_LISTEN": f"127.0.0.1:{DB_PORT}",
           "CARDB_TOKENS": ",".join(f"{k}:{v}" for k, v in TOK.items())}
    db = subprocess.Popen([CARDB_BIN, "serve"], env=env, stdout=open(BASE / "cardb.log", "w"), stderr=subprocess.STDOUT)
    procs = [db]
    signal.signal(signal.SIGTERM, lambda *_: [p.terminate() for p in procs] and sys.exit(0))
    wait(f"http://127.0.0.1:{DB_PORT}/healthz", db, "cardb")
    ph = {}
    creds = json.loads((PHOTOS / "credits.json").read_text()) if (PHOTOS / "credits.json").exists() else []
    order = {"front": 0, "side": 1, "rear": 2, "interior": 3}
    for c in sorted(creds, key=lambda c: (c["file"], order.get(c.get("view"), 9))):
        key = KEYMAP.get(re.sub(r"-\d+\.jpe?g$", "", c["file"]))
        if not key or c["file"] in SKIP:
            continue
        ph.setdefault(key, []).append((c["file"], c.get("view", "")))
    for k in ph:
        ph[k].sort(key=lambda fv: order.get(fv[1], 9))
    print("photo keys:", sorted(ph), flush=True)
    ids = seed(ph)
    story(ids)
    print("ids", json.dumps(ids), flush=True)
    web = REPO / "web"
    wenv = {"PATH": os.environ["PATH"], "HOST": "127.0.0.1", "PORT": str(WEB_PORT), "NODE_ENV": "production",
            "CARDB_URL": f"http://127.0.0.1:{DB_PORT}", "CARDB_WEB_TOKENS": f"{OWNER}:{TOK[OWNER]},{VIEWER}:{TOK[VIEWER]}"}
    w = subprocess.Popen(["node", "./dist/server/entry.mjs"], cwd=web, env=wenv, stdout=open(BASE / "web.log", "w"), stderr=subprocess.STDOUT)
    procs.append(w)
    wait(f"http://127.0.0.1:{WEB_PORT}/health", w, "web")
    print(f"READY web http://127.0.0.1:{WEB_PORT} cardb http://127.0.0.1:{DB_PORT}", flush=True)
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
