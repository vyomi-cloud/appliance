package main

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"io"
	"net/http"
	"strings"
	"time"
)

func lowerTrim(s string) string { return strings.ToLower(strings.TrimSpace(s)) }

func b64encode(s string) string { return base64.StdEncoding.EncodeToString([]byte(s)) }

func randHex() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// httpGet does a GET with a timeout, returning (body, ok).
func httpGet(url string, timeout time.Duration) (string, bool) {
	client := &http.Client{Timeout: timeout}
	resp, err := client.Get(url)
	if err != nil {
		return "", false
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		return "", false
	}
	b, _ := io.ReadAll(resp.Body)
	return string(b), true
}

// httpOK reports whether a GET returns a non-error status within the timeout.
func httpOK(url string, timeout time.Duration) bool {
	_, ok := httpGet(url, timeout)
	return ok
}
