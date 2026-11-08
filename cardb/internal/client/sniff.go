package client

import (
	"io"
	"net/http"
	"os"
	"strings"
)

// SniffType returns the MIME type of file content from its leading bytes: http.DetectContentType,
// plus the ISO-BMFF image formats it doesn't know (HEIC/HEIF/AVIF, as saved by iPhones).
func SniffType(head []byte) string {
	if len(head) >= 12 && string(head[4:8]) == "ftyp" {
		switch string(head[8:12]) {
		case "heic", "heix", "hevc", "hevx", "heim", "heis":
			return "image/heic"
		case "mif1", "msf1", "heif":
			return "image/heif"
		case "avif", "avis":
			return "image/avif"
		}
	}
	return http.DetectContentType(head)
}

// SniffFile sniffs the first 512 bytes of a file.
func SniffFile(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	head := make([]byte, 512)
	n, err := io.ReadFull(f, head)
	if err != nil && err != io.ErrUnexpectedEOF && err != io.EOF {
		return "", err
	}
	return SniffType(head[:n]), nil
}

// IsImage reports whether a sniffed MIME type is an image.
func IsImage(mime string) bool { return strings.HasPrefix(mime, "image/") }
