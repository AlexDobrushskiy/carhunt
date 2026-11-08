package api

import "math"

// Horsepower converts kW to rounded metric horsepower (PS), as displayed to users.
func Horsepower(kw float64) int { return int(math.Round(kw * 1.36)) }
