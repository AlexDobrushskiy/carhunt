package imaging

import (
	"bytes"
	"image"
	"image/color"
	"image/jpeg"
	"image/png"
	"math/rand"
	"os"
	"strings"
	"sync"
	"testing"

	"github.com/gen2brain/avif"
)

func blocks(seed int64, w, h int) *image.RGBA {
	rng := rand.New(rand.NewSource(seed))
	var cells [8][8]color.RGBA
	for y := range 8 {
		for x := range 8 {
			cells[y][x] = color.RGBA{uint8(rng.Intn(256)), uint8(rng.Intn(256)), uint8(rng.Intn(256)), 255}
		}
	}
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for y := range h {
		for x := range w {
			img.Set(x, y, cells[y*8/h][x*8/w])
		}
	}
	return img
}

// degrade adds per-pixel noise and crops a 2 % border, like a re-uploaded ad photo.
func degrade(img *image.RGBA, seed int64) image.Image {
	rng := rand.New(rand.NewSource(seed))
	b := img.Bounds()
	dx, dy := b.Dx()*2/100, b.Dy()*2/100
	out := image.NewRGBA(image.Rect(0, 0, b.Dx()-2*dx, b.Dy()-2*dy))
	clamp := func(v int) uint8 { return uint8(max(0, min(255, v))) }
	for y := range out.Bounds().Dy() {
		for x := range out.Bounds().Dx() {
			c := img.RGBAAt(x+dx, y+dy)
			n := rng.Intn(41) - 20
			out.Set(x, y, color.RGBA{clamp(int(c.R) + n), clamp(int(c.G) + n), clamp(int(c.B) + n), 255})
		}
	}
	return out
}

func encode(t *testing.T, img image.Image, q int) []byte {
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, img, &jpeg.Options{Quality: q}); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func TestPHashDistances(t *testing.T) {
	orig, err := Prepare(encode(t, blocks(1, 1200, 800), 90))
	if err != nil {
		t.Fatal(err)
	}
	near, err := Prepare(encode(t, degrade(blocks(1, 1000, 667), 7), 60))
	if err != nil {
		t.Fatal(err)
	}
	other, err := Prepare(encode(t, blocks(2, 1200, 800), 90))
	if err != nil {
		t.Fatal(err)
	}
	if d := Hamming(orig.PHash, near.PHash); d == 0 || d > 6 {
		t.Fatalf("degraded copy distance = %d, want 1..6", d)
	}
	if d := Hamming(orig.PHash, other.PHash); d < 16 {
		t.Fatalf("unrelated distance = %d, want ≥ 16", d)
	}
	if orig.SHA256 == near.SHA256 {
		t.Fatal("different bytes, same sha")
	}
}

func TestPrepareResizesAndConverts(t *testing.T) {
	var buf bytes.Buffer
	if err := png.Encode(&buf, blocks(3, 3000, 1500)); err != nil {
		t.Fatal(err)
	}
	p, err := Prepare(buf.Bytes())
	if err != nil {
		t.Fatal(err)
	}
	if p.Width != MaxStoredPx || p.Height != 1000 {
		t.Fatalf("stored size = %dx%d", p.Width, p.Height)
	}
	cfg, format, err := image.DecodeConfig(bytes.NewReader(p.JPEG))
	if err != nil || format != "jpeg" || cfg.Width != MaxStoredPx {
		t.Fatalf("stored jpeg = %v %s %v", cfg, format, err)
	}
	thumb, err := Resize(p.JPEG, ThumbWidth)
	if err != nil {
		t.Fatal(err)
	}
	if cfg, _, _ := image.DecodeConfig(bytes.NewReader(thumb)); cfg.Width != ThumbWidth || cfg.Height != 200 {
		t.Fatalf("thumb = %dx%d", cfg.Width, cfg.Height)
	}
	if _, err := Prepare([]byte("nope")); err == nil {
		t.Fatal("garbage decoded")
	}
}

func TestEXIFOrientation(t *testing.T) {
	// Minimal JPEG with an APP1 Exif segment carrying orientation 6 (rotate 90° CW).
	src := encode(t, blocks(4, 40, 20), 90)
	tiff := []byte{'M', 'M', 0, 42, 0, 0, 0, 8, 0, 1, 0x01, 0x12, 0, 3, 0, 0, 0, 1, 0, 6, 0, 0, 0, 0, 0, 0, 0, 0}
	seg := append([]byte("Exif\x00\x00"), tiff...)
	app1 := append([]byte{0xFF, 0xE1, byte((len(seg) + 2) >> 8), byte(len(seg) + 2)}, seg...)
	data := append(append([]byte{0xFF, 0xD8}, app1...), src[2:]...)
	if o := jpegOrientation(data); o != 6 {
		t.Fatalf("orientation = %d", o)
	}
	p, err := Prepare(data)
	if err != nil {
		t.Fatal(err)
	}
	if p.Width != 20 || p.Height != 40 {
		t.Fatalf("rotated size = %dx%d", p.Width, p.Height)
	}
}

// testdata/blocks.heic is blocks(41, 400, 300) converted with macOS `sips -s format heic`.
func TestAVIFAndHEIC(t *testing.T) {
	ref, err := Prepare(encode(t, blocks(41, 400, 300), 90))
	if err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	if err := avif.Encode(&buf, blocks(41, 400, 300), avif.Options{Quality: 80, Speed: 10}); err != nil {
		t.Fatal(err)
	}
	avifData := buf.Bytes()
	heicData, err := os.ReadFile("testdata/blocks.heic")
	if err != nil {
		t.Fatal(err)
	}
	for name, data := range map[string][]byte{"avif": avifData, "heic": heicData} {
		if isoFormat(data) == "" {
			t.Fatalf("%s not sniffed as ISO-BMFF", name)
		}
		p, err := Prepare(data)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if p.Width != 400 || p.Height != 300 || Hamming(p.PHash, ref.PHash) > 6 {
			t.Fatalf("%s: %dx%d, phash distance %d", name, p.Width, p.Height, Hamming(p.PHash, ref.PHash))
		}
		if _, format, _ := image.DecodeConfig(bytes.NewReader(p.JPEG)); format != "jpeg" {
			t.Fatalf("%s stored as %s", name, format)
		}
	}
	// Concurrent decodes (upserts fetch photos in parallel).
	var wg sync.WaitGroup
	errs := make(chan error, 8)
	for range 8 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := Prepare(avifData); err != nil {
				errs <- err
			}
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Fatal(err)
	}
	// A truncated AVIF gets a named error, not "unknown format".
	_, err = Prepare(avifData[:40])
	if err == nil || !strings.Contains(err.Error(), "AVIF image could not be decoded") {
		t.Fatalf("broken avif error = %v", err)
	}
}
