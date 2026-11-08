// Package imaging decodes uploaded photos, normalizes them to JPEG, computes a 64-bit DCT
// perceptual hash and renders resized variants.
package imaging

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"image"
	"image/color"
	"image/draw"
	_ "image/gif" // register decoder
	"image/jpeg"
	_ "image/png" // register decoder
	"math"
	"math/bits"
	"sort"

	// AVIF/HEIC decoders run libavif/libheif as WebAssembly (wazero): pure Go, CGO off.
	// Needed because CDNs (Subito) serve AVIF regardless of Accept, and iPhone photos are HEIC.
	_ "github.com/gen2brain/avif"
	_ "github.com/gen2brain/heic"
	xdraw "golang.org/x/image/draw"
	_ "golang.org/x/image/webp" // register decoder
)

const (
	MaxStoredPx = 2000 // longest side of the stored original
	JPEGQuality = 85
	ThumbWidth  = 400
	MediumWidth = 1000
	MaxPixels   = 50_000_000 // refuse decode bombs before allocating
)

// Prepared is a decoded photo ready to store.
type Prepared struct {
	SHA256 string // hex sha256 of the uploaded bytes (identity)
	PHash  uint64
	Width  int // of the stored JPEG
	Height int
	JPEG   []byte
}

// Prepare decodes JPEG/PNG/GIF/WebP/AVIF/HEIC bytes, applies EXIF orientation, caps the size and re-encodes as JPEG.
func Prepare(data []byte) (*Prepared, error) {
	if len(data) == 0 {
		return nil, errors.New("empty image")
	}
	cfg, _, err := image.DecodeConfig(bytes.NewReader(data))
	if err != nil {
		if f := isoFormat(data); f != "" {
			return nil, fmt.Errorf("%s image could not be decoded (%v); upload a JPEG, PNG or WebP", f, err)
		}
		return nil, fmt.Errorf("decode image: %w", err)
	}
	if cfg.Width <= 0 || cfg.Height <= 0 || cfg.Width*cfg.Height > MaxPixels {
		return nil, fmt.Errorf("image %dx%d exceeds %d MP", cfg.Width, cfg.Height, MaxPixels/1_000_000)
	}
	img, format, err := image.Decode(bytes.NewReader(data))
	if err != nil {
		return nil, fmt.Errorf("decode image: %w", err)
	}
	if format == "jpeg" {
		img = applyOrientation(img, jpegOrientation(data))
	}
	img = fit(img, MaxStoredPx)
	out, err := encodeJPEG(img)
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(data)
	b := img.Bounds()
	return &Prepared{
		SHA256: hex.EncodeToString(sum[:]),
		PHash:  PHash(img),
		Width:  b.Dx(),
		Height: b.Dy(),
		JPEG:   out,
	}, nil
}

// isoFormat names AVIF/HEIC files (ISO-BMFF `ftyp` box) so a failed decode gets a clear error; "" otherwise.
func isoFormat(data []byte) string {
	if len(data) < 12 || string(data[4:8]) != "ftyp" {
		return ""
	}
	brands := []string{string(data[8:12])}
	if size := int(binary.BigEndian.Uint32(data[:4])); size >= 16 && size <= len(data) {
		for i := 16; i+4 <= size; i += 4 {
			brands = append(brands, string(data[i:i+4]))
		}
	}
	for _, b := range brands {
		switch b {
		case "avif", "avis":
			return "AVIF"
		}
	}
	for _, b := range brands {
		switch b {
		case "heic", "heix", "heim", "heis", "hevc", "hevx", "mif1", "msf1":
			return "HEIC"
		}
	}
	return ""
}

// Resize decodes a JPEG and returns it scaled to the given width (never upscaled).
func Resize(jpegData []byte, width int) ([]byte, error) {
	img, _, err := image.Decode(bytes.NewReader(jpegData))
	if err != nil {
		return nil, fmt.Errorf("decode image: %w", err)
	}
	b := img.Bounds()
	if b.Dx() > width {
		h := int(math.Round(float64(b.Dy()) * float64(width) / float64(b.Dx())))
		img = scale(img, width, max(h, 1), xdraw.CatmullRom)
	}
	return encodeJPEG(img)
}

// Hamming returns the number of differing bits.
func Hamming(a, b uint64) int { return bits.OnesCount64(a ^ b) }

// PHash is the classic DCT perceptual hash: 32x32 grayscale → 2-D DCT → top-left 8x8 block,
// one bit per coefficient above the median (DC term excluded from the median).
func PHash(img image.Image) uint64 {
	const n = 32
	small := scale(img, n, n, xdraw.ApproxBiLinear)
	var px [n][n]float64
	for y := range n {
		for x := range n {
			r, g, b, _ := small.At(x, y).RGBA()
			px[y][x] = 0.299*float64(r>>8) + 0.587*float64(g>>8) + 0.114*float64(b>>8)
		}
	}
	coef := dct2(px)
	vals := make([]float64, 0, 64)
	for y := range 8 {
		for x := range 8 {
			vals = append(vals, coef[y][x])
		}
	}
	sorted := append([]float64(nil), vals[1:]...)
	sort.Float64s(sorted)
	median := (sorted[len(sorted)/2-1] + sorted[len(sorted)/2]) / 2
	var h uint64
	for i, v := range vals {
		if v > median {
			h |= 1 << uint(63-i)
		}
	}
	return h
}

// dct2 computes the low-frequency 8x8 corner of a 32x32 2-D DCT-II.
func dct2(px [32][32]float64) [8][8]float64 {
	const n = 32
	var cosT [8][n]float64
	for u := range 8 {
		for x := range n {
			cosT[u][x] = math.Cos(float64(2*x+1) * float64(u) * math.Pi / (2 * n))
		}
	}
	var rows [n][8]float64 // DCT along x for each row
	for y := range n {
		for u := range 8 {
			var s float64
			for x := range n {
				s += px[y][x] * cosT[u][x]
			}
			rows[y][u] = s
		}
	}
	var out [8][8]float64
	for v := range 8 {
		for u := range 8 {
			var s float64
			for y := range n {
				s += rows[y][u] * cosT[v][y]
			}
			out[v][u] = s
		}
	}
	return out
}

func fit(img image.Image, maxPx int) image.Image {
	b := img.Bounds()
	w, h := b.Dx(), b.Dy()
	if w <= maxPx && h <= maxPx {
		return img
	}
	if w >= h {
		return scale(img, maxPx, max(1, int(math.Round(float64(h)*float64(maxPx)/float64(w)))), xdraw.CatmullRom)
	}
	return scale(img, max(1, int(math.Round(float64(w)*float64(maxPx)/float64(h)))), maxPx, xdraw.CatmullRom)
}

func scale(img image.Image, w, h int, s xdraw.Scaler) image.Image {
	dst := image.NewRGBA(image.Rect(0, 0, w, h))
	s.Scale(dst, dst.Bounds(), img, img.Bounds(), xdraw.Over, nil)
	return dst
}

func encodeJPEG(img image.Image) ([]byte, error) {
	// Flatten transparency onto white so PNG/WebP alpha doesn't turn black.
	b := img.Bounds()
	flat := image.NewRGBA(image.Rect(0, 0, b.Dx(), b.Dy()))
	draw.Draw(flat, flat.Bounds(), &image.Uniform{C: color.White}, image.Point{}, draw.Src)
	draw.Draw(flat, flat.Bounds(), img, b.Min, draw.Over)
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, flat, &jpeg.Options{Quality: JPEGQuality}); err != nil {
		return nil, fmt.Errorf("encode jpeg: %w", err)
	}
	return buf.Bytes(), nil
}
