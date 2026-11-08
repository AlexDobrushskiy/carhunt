"""normalize: synthetic ads in 6 languages + regression cases (values synthetic)."""
import pytest

from carhunt.discover import normalize as n
from carhunt.sites.model import Card, RawAd, Seller


def ad(**kw) -> RawAd:
    base = dict(url="https://x.example.invalid/ad/1", site="x", site_ref="1", make="Volkswagen", model="ID.4",
                title="Volkswagen ID.4 Pro", price=30000, km=20000, first_registration="2023-04", fuel="Elektro",
                country="DE", seller=Seller(type="dealer", city="Teststadt"))
    seller = kw.pop("seller", None)
    base.update(kw)
    if seller:
        base["seller"] = seller
    return RawAd(**base)


def opts(lst):
    return {k: v for k, (v, _) in lst.options.items()}


# --- six languages ---------------------------------------------------------------

LANG = {
    "de": ("Wärmepumpe, Panorama-Glasdach, elektrisch verstellbare Sitze mit Memory, Heckklappe elektrisch, "
           "Anhängerkupplung. Unfallfrei, Scheckheftgepflegt, 1. Hand.",
           {"heat_pump", "pano", "electric_seats", "memory_seats", "power_tailgate", "towbar"},
           {"accident_free", "service_history", "owners"}),
    "fr": ("Pompe à chaleur, toit panoramique, sièges électriques à mémoire, hayon électrique, attelage. "
           "Première main, jamais accidenté, carnet d'entretien à jour.",
           {"heat_pump", "pano", "electric_seats", "memory_seats", "power_tailgate", "towbar"},
           {"accident_free", "service_history", "owners"}),
    "es": ("Bomba de calor, techo solar panorámico, asientos eléctricos con memoria, portón trasero eléctrico. "
           "Único propietario, sin accidentes, libro de mantenimiento.",
           {"heat_pump", "pano", "electric_seats", "memory_seats", "power_tailgate"},
           {"accident_free", "service_history", "owners"}),
    "it": ("Pompa di calore, tetto panoramico, sedili elettrici con memoria, portellone elettrico, gancio traino. "
           "Unico proprietario, nessun incidente, tagliandi certificati.",
           {"heat_pump", "pano", "electric_seats", "memory_seats", "power_tailgate", "towbar"},
           {"accident_free", "service_history", "owners"}),
    "pt": ("Bomba de calor, teto panorâmico, bancos elétricos com memória, mala elétrica, engate. "
           "Primeiro dono, sem acidentes, revisões em dia na marca.",
           {"heat_pump", "pano", "electric_seats", "memory_seats", "power_tailgate", "towbar"},
           {"accident_free", "service_history", "owners"}),
    "nl": ("Warmtepomp, panoramadak, elektrisch verstelbare stoelen met geheugen, elektrische achterklep, trekhaak. "
           "Eerste eigenaar, schadevrij, dealer onderhouden.",
           {"heat_pump", "pano", "electric_seats", "memory_seats", "power_tailgate", "towbar"},
           {"accident_free", "service_history", "owners"}),
}


@pytest.mark.parametrize("lang", sorted(LANG))
def test_options_and_facts_per_language(lang):
    text, want_opts, want_facts = LANG[lang]
    lst = n.from_ad(ad(description=text))
    assert want_opts <= set(opts(lst)), (lang, opts(lst))
    assert all(opts(lst)[k] == "yes" for k in want_opts)
    assert want_facts <= set(lst.facts), (lang, lst.facts)
    assert all(src == "ad_text" for k, (_, src) in lst.options.items())


def test_stated_absence_is_no_and_silence_is_unknown():
    lst = n.from_ad(ad(description="Manuelle Sitzverstellung, ohne Panoramadach."))
    assert opts(lst) == {"electric_seats": "no", "pano": "no"}
    assert "heat_pump" not in n.from_ad(ad(description="Nice car.")).options


@pytest.mark.parametrize("text,key", [
    ("Hayon assisté électriquement pour ouverture et fermeture", "power_tailgate"),
    ("Elektrisch bedienbare achterklep", "power_tailgate"),
    ("Portón trasero eléctrico", "power_tailgate"),
])
def test_tailgate_phrases(text, key):
    assert opts(n.from_ad(ad(description=text)))[key] == "yes"


def test_clause_unless_and_loose_numbers():
    lst = n.from_ad(ad(description="Panoramic view camera. Range 360 km. Memory parking assist."))
    assert "pano" not in lst.options and "camera_360" not in lst.options and "memory_seats" not in lst.options
    assert opts(n.from_ad(ad(description="Area View 360° camera")))["camera_360"] == "yes"


# --- flags -----------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Leasingübernahme möglich", "Reprise de leasing LOA", "Subentro leasing",
                                  "cuota / mes 399", "Lease overname mogelijk"])
def test_lease_transfer(text):
    assert "lease_transfer" in n.from_ad(ad(description=text)).flags


@pytest.mark.parametrize("text", ["Unfallwagen, nicht fahrbereit", "auto incidentata", "vehículo accidentado",
                                  "dégâts de grêle", "Hagelschaden", "airbag ausgelöst"])
def test_damage_flags_suspect(text):
    lst = n.from_ad(ad(description=text))
    assert "damaged" in lst.flags and lst.facts["deal_flag"][0].startswith("suspect")


def test_accident_free_is_not_damage():
    lst = n.from_ad(ad(description="Unfallfrei, sans accident, sem sinistros"))
    assert "damaged" not in lst.flags and "accident_free" in lst.facts


def test_reseller_on_private_ad():
    lst = n.from_ad(ad(description="Verkauf im Kundenauftrag", seller=Seller(type="private")))
    assert lst.seller_type == "reseller"


def test_china_market_vin_flag_only_for_listed_wmi():
    assert "china_market_vin" in n.from_ad(ad(vin="LFVSYN00000000001")).flags  # privacy-check: allow (synthetic)
    assert "china_market_vin" not in n.from_ad(ad(vin="LRWSYN00000000001")).flags  # privacy-check: allow (synthetic)


# --- prices ----------------------------------------------------------------------

def test_net_price_to_gross_by_country():
    lst = n.from_ad(ad(price=30000, price_is_net=True, country="DE"))
    assert lst.price == 35700 and "net_price" in lst.flags
    assert lst.facts["source_net_price_eur"][0] == "30000"
    assert n.from_ad(ad(price=30000, price_is_net=True, country="LU")).price == 35100


def test_net_price_unknown_vat_country_has_no_price():
    lst = n.from_ad(ad(price=30000, price_is_net=True, country="XX"))
    assert lst.price is None and "net_price_unknown_vat" in lst.flags


@pytest.mark.parametrize("text,expected", [
    ("Precio al contado: 41780 euros. Precio al contado: 41.780€. Oferta financiación:36.280€", 41780),
    ("Precio al contado: 41780 euros. Ejemplo precio al contado:30000 euros.", None),
    ("Cuota al mes: 500 euros.", None),
    ("PVP CONTADO: 38.890 €\nPVP FINANCIADO: 36.890 €", 38890),
])
def test_cash_price(text, expected):
    assert n.cash_price(text) == expected


def test_es_cash_price_beats_finance_headline():
    lst = n.from_ad(ad(country="ES", price=36890, description="PVP CONTADO: 38.890 €. PVP FINANCIADO: 36.890 €"))
    assert lst.price == 38890 and lst.facts["headline_conditional_price_eur"][0] == "36890"


@pytest.mark.parametrize("text,price", [
    ("Prezzo IVA esclusa.", 36600),
    ("Il prezzo è da ritenere al netto di Iva, con possibilità di fatturazione.", 36600),
    ("Batteria 82 kWh lordi / 77 kWh netto.", 30000),          # battery "netto" is not a price
    ("Pacchetto opzionale 231 euro IVA esclusa.", 30000),       # an option price is not the ask
])
def test_it_net_ask(text, price):
    assert n.from_ad(ad(country="IT", price=30000, description=text)).price == price


def test_net_wording_only_flags_review():
    lst = n.from_ad(ad(price=30000, description="Exportpreis netto"))
    assert lst.price == 30000 and "price_basis_review" in lst.facts


@pytest.mark.parametrize("raw,val", [("299.0", 299), ("45000.0", 45000), ("41.900", 41900), ("41.900,50", 41900.5),
                                     ("28990.99", 28990.99), (None, None)])
def test_number(raw, val):
    assert n.number(raw) == val


# --- power / drive / fuel --------------------------------------------------------

@pytest.mark.parametrize("title,desc,kw", [
    ("ID.4 77 kWh 210 kW (286 ch)", "", 210),
    ("ID.4 77 kWh 204pk", "", 150),
    ("ID.4 Pro", "Vermogen: 210 kW", 210),
    ("ID.4 Pro 77kw 204CV", "", 150),
    ("ID.4 Pro DC 210 kW", "", None),
    ("ID.4 Pro", "DC laden 135 kW", None),
    ("ID.4 Pro 150 kW 286 PS", "", None),        # kW and hp disagree
])
def test_power(title, desc, kw):
    assert n.advertised_power_kw(title, desc) == kw


def test_power_from_structured_hp():
    assert n.from_ad(ad(power_hp=204, title="ID.4")).power_kw == 150


@pytest.mark.parametrize("label,drive", [("Achterwielaandrijving", "rwd"), ("Frontantrieb", "fwd"),
                                         ("Allradantrieb", "awd"), ("REAR", "rwd"), ("FOUR", "awd")])
def test_drive_site_label(label, drive):
    assert n.from_ad(ad(drive=label)).drive == drive


def test_drive_title_awd_beats_site_field():
    assert n.from_ad(ad(drive="rear", title="ID.4 Pro 4MOTION")).drive == "awd"


def test_alloy_wheel_count_is_not_4x4():
    assert n.from_ad(ad(title="ID.4 Pro", description="4 Leichtmetallräder. Heckantrieb.")).drive == "rwd"


@pytest.mark.parametrize("label,fuel", [("Elektro", "bev"), ("electric_hybrid", "bev"), ("Híbrido enchufable", "phev"),
                                        ("hybride_plugin", "phev"), ("Gasolina", "petrol"), ("Diesel", "diesel"),
                                        ("Elettrica", "bev"), ("Hybride", "hev")])
def test_fuel(label, fuel):
    assert n.fuel_of(label) == fuel


# --- location / phones / dates ---------------------------------------------------

@pytest.mark.parametrize("country,city,postcode,region", [
    ("ES", "La Laguna", "38205", "ES-CN"),
    ("ES", "La Laguna", None, "ES-CN"),
    ("ES", "Telde", "35200", "ES-CN"),
    ("PT", "Funchal", "9000-100", "PT-30"),
    ("PT", "Ponta Delgada", "9500-001", "PT-20"),
    ("PT", "Lisboa", "1900-100", None),
    ("PT", "Rua da Madeira, Lisboa", "1900-100", None),     # postcode wins over a street name
    ("ES", "Palma", "07001", "ES-IB"),
])
def test_region(country, city, postcode, region):
    lst = n.from_ad(ad(country=country, seller=Seller(type="dealer", city=city, postcode=postcode)))
    assert lst.region == region


@pytest.mark.parametrize("raw,country,out", [
    ("0255500000", "IT", "390255500000"),
    ("3555000000", "IT", "393555000000"),
    ("3905550000", "IT", "3905550000"),
    ("+33 6 55 50 00 00", "IT", "33655500000"),
    ("655500000", "ES", "34655500000"),
    ("915550000", "PT", "351915550000"),
    ("0049 30 5550000", "DE", "49305550000"),
    ("030 5550000", "DE", "49305550000"),
    ("06 55 50 00 00", "FR", "33655500000"),
    ("06-55500000", "NL", "31655500000"),
])
def test_canonical_phone(raw, country, out):
    assert n.canonical_phone(raw, country) == out


@pytest.mark.parametrize("raw,year,out", [("2025", None, ("2025-01", True)), ("2025-1", None, ("2025-01", False)),
                                          ("03/2024", None, ("2024-03", False)), (None, 2022, ("2022-01", True)),
                                          ("", None, (None, False))])
def test_reg_date(raw, year, out):
    assert n.reg_date(raw, year) == out


def test_card_listing_and_upsert_shape():
    card = Card(url="https://x.example.invalid/ad/9", site="x", site_ref="9", title="Skoda Enyaq 85 210 kW",
                price=33000, km=10000, first_registration="2024", make="Skoda", model="Enyaq", country="ES",
                seller_type="private", location="Testciudad")
    lst = n.from_card(card)
    body = lst.to_upsert()
    assert body["price_vat"] == "gross" and body["reg_date"] == "2024-01"
    assert body["seller"]["contacts"] == [{"kind": "site_chat", "value": card.url}]
    assert "photo_urls" not in body and lst.detail is False
    assert body["facts"]["reg_precision"]["source"] == "ad_text"
