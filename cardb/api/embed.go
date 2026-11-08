// Package apispec embeds the OpenAPI contract so the server can serve it.
package apispec

import _ "embed"

// Spec is api/openapi.yaml.
//
//go:embed openapi.yaml
var Spec []byte
