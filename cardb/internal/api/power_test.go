package api

import "testing"

func TestHorsepower(t *testing.T) {
	for _, tc := range []struct {
		kw float64
		hp int
	}{{0, 0}, {100, 136}, {150, 204}, {125, 170}, {125.4, 171}, {210, 286}, {220, 299}} {
		if got := Horsepower(tc.kw); got != tc.hp {
			t.Errorf("Horsepower(%v) = %d, want %d", tc.kw, got, tc.hp)
		}
	}
}
