package api

import "strings"

// Fuel and gearbox words as ads write them (PT/ES/FR/DE/IT/NL/EN), folded (lower case, no accents, "-"/"_" → " ").
var fuelSynonyms = map[string]string{
	"electric": "bev", "electrico": "bev", "eletrico": "bev", "electrique": "bev", "elektro": "bev", "elektrisch": "bev",
	"elettrica": "bev", "elettrico": "bev", "ev": "bev", "bev": "bev", "100% electric": "bev", "100% electrico": "bev",
	"100% eletrico": "bev", "electric vehicle": "bev",
	"plug in": "phev", "plugin": "phev", "plug in hybrid": "phev", "plugin hybrid": "phev", "phev": "phev",
	"hibrido plug in": "phev", "hybride rechargeable": "phev", "plug in hybride": "phev", "ibrida plug in": "phev",
	"hybrid": "hev", "full hybrid": "hev", "hibrido": "hev", "hybride": "hev", "ibrida": "hev", "ibrido": "hev", "hev": "hev",
	"mild hybrid": "mhev", "mhev": "mhev", "hibrido suave": "mhev", "hibrido ligero": "mhev", "mild hybride": "mhev",
	"petrol": "petrol", "gasoline": "petrol", "gasolina": "petrol", "benzin": "petrol", "benzine": "petrol",
	"benzina": "petrol", "essence": "petrol",
	"diesel": "diesel", "gasoleo": "diesel", "gasoil": "diesel", "gazole": "diesel",
	"lpg": "lpg", "gpl": "lpg", "autogas": "lpg", "glp": "lpg",
	"cng": "cng", "gnv": "cng", "gnc": "cng", "metano": "cng", "erdgas": "cng", "aardgas": "cng",
	"hydrogen": "hydrogen", "hidrogeno": "hydrogen", "hidrogenio": "hydrogen", "wasserstoff": "hydrogen",
	"hydrogene": "hydrogen", "idrogeno": "hydrogen", "fcev": "hydrogen", "h2": "hydrogen",
	"unknown": "unknown",
}

var gearboxSynonyms = map[string]string{
	"manual": "manual", "manuell": "manual", "manuelle": "manual", "manuale": "manual", "handgeschakeld": "manual",
	"schaltgetriebe": "manual", "mecanica": "manual", "mecanique": "manual",
	"automatic": "automatic", "automatico": "automatic", "automatica": "automatic", "automatik": "automatic",
	"automatique": "automatic", "automaat": "automatic", "auto": "automatic", "dsg": "automatic", "dct": "automatic",
	"cvt": "automatic", "edc": "automatic", "s tronic": "automatic", "tiptronic": "automatic", "steptronic": "automatic",
	"unknown": "unknown",
}

var foldAccents = strings.NewReplacer("á", "a", "à", "a", "â", "a", "ã", "a", "ä", "a", "é", "e", "è", "e", "ê", "e", "ë", "e",
	"í", "i", "ì", "i", "î", "i", "ï", "i", "ó", "o", "ò", "o", "ô", "o", "õ", "o", "ö", "o", "ú", "u", "ù", "u", "û", "u",
	"ü", "u", "ç", "c", "ñ", "n", "-", " ", "_", " ")

func foldWord(s string) string {
	return strings.Join(strings.Fields(foldAccents.Replace(strings.ToLower(s))), " ")
}

// NormFuel maps a fuel word to the Fuels enum ("" if unrecognised): "Elétrico" → bev, "Plug-in" → phev.
func NormFuel(s string) string { return fuelSynonyms[foldWord(s)] }

// NormGearbox maps a gearbox word to the Gearboxes enum ("" if unrecognised): "Automático", "DSG" → automatic.
func NormGearbox(s string) string { return gearboxSynonyms[foldWord(s)] }
