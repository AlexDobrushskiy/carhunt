package geo

import (
	"slices"
	"sort"
	"strings"
)

// Region is an ISO 3166-2 subdivision a buyer may exclude (islands, overseas departments): cars are matched by
// place names in their city text, folded whole words.
type Region struct {
	Country string
	Name    string
	Places  []string // folded place names
}

// Regions: ISO 3166-2 code → region. Place lists name the region, its islands and main towns; names shared with the
// mainland ("Santa Cruz", "Saint-Denis", "Lagoa") are left out on purpose.
var Regions = map[string]Region{
	"PT-20": {"PT", "Azores", []string{"acores", "azores", "ponta delgada", "angra do heroismo", "praia da vitoria",
		"ribeira grande", "sao miguel", "terceira", "faial", "ilha do pico", "sao jorge", "santa maria acores", "flores acores"}},
	"PT-30": {"PT", "Madeira", []string{"madeira", "funchal", "porto santo", "camara de lobos", "machico", "canico",
		"ribeira brava", "calheta madeira"}},
	"ES-CN": {"ES", "Canary Islands", []string{"canarias", "canary", "islas canarias", "las palmas", "gran canaria", "tenerife",
		"lanzarote", "fuerteventura", "la palma", "la gomera", "el hierro", "arrecife", "puerto del rosario",
		"santa cruz de tenerife", "telde", "maspalomas", "adeje", "arona", "la laguna", "san cristobal de la laguna"}},
	"ES-IB": {"ES", "Balearic Islands", []string{"baleares", "balears", "illes balears", "islas baleares", "mallorca",
		"majorca", "menorca", "minorca", "ibiza", "eivissa", "formentera", "palma de mallorca", "manacor", "mahon",
		"ciutadella", "llucmajor", "calvia", "marratxi"}},
	"FR-20R": {"FR", "Corsica", []string{"corse", "corsica", "ajaccio", "bastia", "porto vecchio"}},
	"FR-971": {"FR", "Guadeloupe", []string{"guadeloupe", "pointe a pitre", "basse terre", "les abymes", "baie mahault"}},
	"FR-972": {"FR", "Martinique", []string{"martinique", "fort de france", "le lamentin"}},
	"FR-973": {"FR", "French Guiana", []string{"guyane", "french guiana", "cayenne", "kourou", "saint laurent du maroni"}},
	"FR-974": {"FR", "Réunion", []string{"reunion", "la reunion", "saint denis de la reunion", "saint paul reunion", "le tampon"}},
	"FR-976": {"FR", "Mayotte", []string{"mayotte", "mamoudzou", "dzaoudzi"}},
	"IT-82":  {"IT", "Sicily", []string{"sicilia", "sicily", "palermo", "catania", "messina", "siracusa", "syracuse", "ragusa", "trapani", "agrigento", "caltanissetta", "enna", "marsala", "gela"}},
	"IT-88":  {"IT", "Sardinia", []string{"sardegna", "sardinia", "cagliari", "sassari", "olbia", "nuoro", "oristano", "alghero", "carbonia"}},
	"GR-M":   {"GR", "Crete", []string{"crete", "kriti", "heraklion", "iraklio", "chania", "rethymno", "agios nikolaos"}},
}

// RegionCodes lists the known region codes, sorted.
func RegionCodes() []string {
	out := make([]string, 0, len(Regions))
	for c := range Regions {
		out = append(out, c)
	}
	sort.Strings(out)
	return out
}

// RegionOf returns the first of codes whose place names occur in city ("" = none). A known car country must match
// the region's country.
func RegionOf(country, city string, codes []string) string {
	f := FoldWords(city)
	if f == "" {
		return ""
	}
	for _, code := range codes {
		r, ok := Regions[strings.ToUpper(code)]
		if !ok || (country != "" && !strings.EqualFold(country, r.Country)) {
			continue
		}
		if slices.ContainsFunc(r.Places, func(p string) bool { return HasPhrase(f, p) }) {
			return strings.ToUpper(code)
		}
	}
	return ""
}
