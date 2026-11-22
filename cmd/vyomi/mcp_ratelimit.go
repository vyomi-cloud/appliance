package main

// Abuse control for the hosted MCP server (D-I4): 60 calls a minute per client with a burst of 20, and 50
// requests a second across the process. In memory only, so an instance forgets everything when it restarts and a
// second instance keeps its own counters — enough for a stateless knowledge server with no sign-in (D-H3).
//
// The client address never reaches the buckets: the key is a salted hash of it, with the salt generated per
// process, so even a memory dump holds no addresses. Nothing here is logged (O-D4).

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"sync"
	"time"
)

const (
	rateLimitPerMinute = 60               // sustained, per client
	rateLimitBurst     = 20               // per client
	rateLimitGlobal    = 50               // requests a second, whole process
	rateLimitIdle      = 10 * time.Minute // a key with a full bucket and no traffic is dropped
	rateLimitMaxKeys   = 50000            // hard cap on the map, so a spray of addresses cannot grow it forever
)

// bucket is a token bucket: `tokens` refill at `rate` a second up to `burst`.
type bucket struct {
	tokens float64
	last   time.Time
}

func (b *bucket) take(now time.Time, rate, burst float64) (bool, time.Duration) {
	if b.last.IsZero() {
		b.tokens, b.last = burst, now
	}
	if d := now.Sub(b.last).Seconds(); d > 0 {
		b.tokens += d * rate
		if b.tokens > burst {
			b.tokens = burst
		}
		b.last = now
	}
	if b.tokens >= 1 {
		b.tokens--
		return true, 0
	}
	// Time until one token is back, rounded up to a whole second for Retry-After.
	wait := time.Duration((1 - b.tokens) / rate * float64(time.Second))
	if wait < time.Second {
		wait = time.Second
	}
	return false, wait
}

type rateLimiter struct {
	mu      sync.Mutex
	salt    [16]byte
	keys    map[uint64]*bucket
	global  bucket
	perSec  float64
	burst   float64
	globalR float64
	now     func() time.Time // tests
}

func newRateLimiter() *rateLimiter {
	l := &rateLimiter{
		keys:    map[uint64]*bucket{},
		perSec:  float64(rateLimitPerMinute) / 60,
		burst:   rateLimitBurst,
		globalR: rateLimitGlobal,
		now:     time.Now,
	}
	if _, err := rand.Read(l.salt[:]); err != nil {
		// Without a salt the keys would be plain address hashes: use the clock rather than nothing.
		binary.LittleEndian.PutUint64(l.salt[:8], uint64(time.Now().UnixNano()))
	}
	return l
}

// hash is the stored key: sha256(salt || addr), truncated. One-way, so the address cannot be read back.
func (l *rateLimiter) hash(addr string) uint64 {
	h := sha256.New()
	h.Write(l.salt[:])
	h.Write([]byte(addr))
	return binary.LittleEndian.Uint64(h.Sum(nil)[:8])
}

// allow reports whether this request may proceed, and how long to wait when it may not.
func (l *rateLimiter) allow(addr string) (bool, time.Duration) {
	now := l.now()
	l.mu.Lock()
	defer l.mu.Unlock()
	if ok, wait := l.global.take(now, l.globalR, l.globalR); !ok {
		return false, wait
	}
	k := l.hash(addr)
	b := l.keys[k]
	if b == nil {
		l.sweep(now)
		b = &bucket{}
		l.keys[k] = b
	}
	return b.take(now, l.perSec, l.burst)
}

// sweep drops idle keys. Called when a new key appears, so an idle server does no work.
func (l *rateLimiter) sweep(now time.Time) {
	if len(l.keys) < rateLimitMaxKeys/2 {
		// Cheap path: only drop keys that have been full and silent for a while.
		for k, b := range l.keys {
			if now.Sub(b.last) > rateLimitIdle {
				delete(l.keys, k)
			}
		}
		return
	}
	for k, b := range l.keys {
		if now.Sub(b.last) > time.Minute || len(l.keys) > rateLimitMaxKeys {
			delete(l.keys, k)
		}
	}
}
