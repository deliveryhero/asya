package s3kv

import (
	"encoding/json"
	"sync"
	"time"
)

// queryCache caches POST /query results with a short TTL.
//
// FindExpired (the mesh-api backstop) fires every ~5s with the same query
// parameters. Without a cache each call triggers a full S3 list+fetch cycle.
// With a 4s TTL only the first call per FindExpired window hits S3; subsequent
// calls within the window return instantly from memory.
//
// Any write (Write, WriteConditional, Delete) must call Invalidate() so that
// callers see the updated state before the TTL expires.
type queryCache struct {
	mu      sync.Mutex
	entries map[string]*cacheEntry
	ttl     time.Duration
}

type cacheEntry struct {
	resp      *QueryResponse
	expiresAt time.Time
}

func newQueryCache(ttl time.Duration) *queryCache {
	return &queryCache{
		entries: make(map[string]*cacheEntry),
		ttl:     ttl,
	}
}

// cacheKey serialises a QueryRequest to a stable string for cache lookup.
func cacheKey(req QueryRequest) string {
	b, _ := json.Marshal(req)
	return string(b)
}

// Get returns a cached response if one exists and has not expired.
func (c *queryCache) Get(req QueryRequest) (*QueryResponse, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.entries[cacheKey(req)]
	if !ok || time.Now().After(e.expiresAt) {
		return nil, false
	}
	return e.resp, true
}

// Set stores a query response in the cache.
func (c *queryCache) Set(req QueryRequest, resp *QueryResponse) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.entries[cacheKey(req)] = &cacheEntry{resp: resp, expiresAt: time.Now().Add(c.ttl)}
}

// Invalidate clears all cached entries. Called on any state mutation (write/delete)
// so subsequent queries reflect the updated document set.
func (c *queryCache) Invalidate() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.entries = make(map[string]*cacheEntry)
}
