package pvckv

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"sync"
	"time"

	"golang.org/x/sys/unix"

	"github.com/deliveryhero/asya/asya-state-proxy-go/internal/pg"
)

// ─── In-memory backend ──────────────────────────────────────────────────────

type memEntry struct {
	value     json.RawMessage
	createdAt time.Time
	updatedAt time.Time
}

type inMemConnector struct {
	mu   sync.RWMutex
	data map[string]*memEntry
}

var _ pg.ServerConnector = (*inMemConnector)(nil)

func newInMemConnector() *inMemConnector {
	return &inMemConnector{data: make(map[string]*memEntry)}
}

func (c *inMemConnector) Read(_ context.Context, key string) (*pg.KVRow, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	e, ok := c.data[key]
	if !ok {
		return nil, fmt.Errorf("read %q: %w", key, pg.ErrNotFound)
	}
	return &pg.KVRow{Key: key, Value: e.value, CreatedAt: e.createdAt, UpdatedAt: e.updatedAt}, nil
}

func (c *inMemConnector) Write(_ context.Context, key string, value json.RawMessage) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now().UTC()
	if e, ok := c.data[key]; ok {
		e.value = value
		e.updatedAt = now
	} else {
		c.data[key] = &memEntry{value: value, createdAt: now, updatedAt: now}
	}
	return nil
}

func (c *inMemConnector) WriteConditional(_ context.Context, key string, value json.RawMessage, ifStatus string) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.data[key]
	if !ok {
		return fmt.Errorf("conditional write %q: %w", key, pg.ErrNotFound)
	}
	var doc map[string]any
	if err := json.Unmarshal(e.value, &doc); err != nil {
		return fmt.Errorf("conditional write %q unmarshal: %w", key, err)
	}
	if status, _ := doc["status"].(string); status != ifStatus {
		return fmt.Errorf("conditional write %q: %w", key, pg.ErrConditionFailed)
	}
	e.value = value
	e.updatedAt = time.Now().UTC()
	return nil
}

func (c *inMemConnector) Exists(_ context.Context, key string) (bool, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	_, ok := c.data[key]
	return ok, nil
}

func (c *inMemConnector) Delete(_ context.Context, key string) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, ok := c.data[key]; !ok {
		return fmt.Errorf("delete %q: %w", key, pg.ErrNotFound)
	}
	delete(c.data, key)
	return nil
}

func (c *inMemConnector) List(_ context.Context, prefix string) ([]string, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	var keys []string
	for k := range c.data {
		if strings.HasPrefix(k, prefix) {
			keys = append(keys, k)
		}
	}
	sort.Strings(keys)
	return keys, nil
}

func (c *inMemConnector) Query(_ context.Context, req pg.QueryRequest) (*pg.QueryResponse, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()

	var rows []pg.KVRow
	for k, e := range c.data {
		if req.Prefix != "" && !strings.HasPrefix(k, req.Prefix) {
			continue
		}
		var doc map[string]any
		if err := json.Unmarshal(e.value, &doc); err != nil {
			continue
		}
		if !matchesFilter(doc, req.Filter) {
			continue
		}
		rows = append(rows, pg.KVRow{Key: k, Value: e.value, CreatedAt: e.createdAt, UpdatedAt: e.updatedAt})
	}

	if len(req.Sort) > 0 {
		sortRows(rows, req.Sort)
	}

	total := len(rows)
	if req.Count {
		return &pg.QueryResponse{Total: total}, nil
	}

	if req.Offset > 0 {
		if req.Offset >= len(rows) {
			rows = nil
		} else {
			rows = rows[req.Offset:]
		}
	}
	if req.Limit > 0 && len(rows) > req.Limit {
		rows = rows[:req.Limit]
	}

	return &pg.QueryResponse{Rows: rows, Total: total}, nil
}

// matchesFilter checks if a document satisfies a Mango-style filter map.
func matchesFilter(doc map[string]any, filter map[string]any) bool {
	for field, condition := range filter {
		val := doc[field]
		switch cond := condition.(type) {
		case map[string]any:
			for op, operand := range cond {
				if !applyOp(val, op, operand) {
					return false
				}
			}
		default:
			if !valuesEqual(val, cond) {
				return false
			}
		}
	}
	return true
}

func applyOp(val any, op string, operand any) bool {
	switch op {
	case "$eq":
		return valuesEqual(val, operand)
	case "$ne":
		return !valuesEqual(val, operand)
	case "$exists":
		want, _ := operand.(bool)
		return (val != nil) == want
	case "$gt":
		return toFloat(val) > toFloat(operand)
	case "$gte":
		return toFloat(val) >= toFloat(operand)
	case "$lt":
		return toFloat(val) < toFloat(operand)
	case "$lte":
		return toFloat(val) <= toFloat(operand)
	case "$in":
		arr, _ := operand.([]any)
		for _, item := range arr {
			if valuesEqual(val, item) {
				return true
			}
		}
		return false
	case "$nin":
		arr, _ := operand.([]any)
		for _, item := range arr {
			if valuesEqual(val, item) {
				return false
			}
		}
		return true
	}
	return false
}

func valuesEqual(a, b any) bool {
	return fmt.Sprintf("%v", a) == fmt.Sprintf("%v", b)
}

func toFloat(v any) float64 {
	switch n := v.(type) {
	case float64:
		return n
	case float32:
		return float64(n)
	case int:
		return float64(n)
	case int64:
		return float64(n)
	}
	return 0
}

func sortRows(rows []pg.KVRow, sortSpec []string) {
	sort.SliceStable(rows, func(i, j int) bool {
		for _, s := range sortSpec {
			desc := strings.HasPrefix(s, "-")
			field := strings.TrimPrefix(s, "-")
			var di, dj map[string]any
			_ = json.Unmarshal(rows[i].Value, &di)
			_ = json.Unmarshal(rows[j].Value, &dj)
			si := fmt.Sprintf("%v", di[field])
			sj := fmt.Sprintf("%v", dj[field])
			if si == sj {
				continue
			}
			if desc {
				return si > sj
			}
			return si < sj
		}
		return false
	})
}

// ─── PVC backend ────────────────────────────────────────────────────────────

type pvcConnector struct {
	cfg Config
	qe  *queryEngine
}

var _ pg.ServerConnector = (*pvcConnector)(nil)

func newPVCConnector(cfg Config) (*pvcConnector, error) {
	if cfg.BaseDir == "" {
		return nil, fmt.Errorf("PVC_KV_BASE_DIR required for pvc mode")
	}
	if cfg.Partition {
		for _, sub := range []string{"active", "archive"} {
			if err := os.MkdirAll(filepath.Join(cfg.BaseDir, sub), 0750); err != nil {
				return nil, fmt.Errorf("mkdir %s: %w", sub, err)
			}
		}
	} else {
		if err := os.MkdirAll(cfg.BaseDir, 0750); err != nil {
			return nil, fmt.Errorf("mkdir base: %w", err)
		}
	}
	qe := newQueryEngine(cfg.BaseDir, cfg.Partition)
	return &pvcConnector{cfg: cfg, qe: qe}, nil
}

func (c *pvcConnector) activePath(key string) string {
	if c.cfg.Partition {
		return filepath.Join(c.cfg.BaseDir, "active", key+".json")
	}
	return filepath.Join(c.cfg.BaseDir, key+".json")
}

func (c *pvcConnector) Read(_ context.Context, key string) (*pg.KVRow, error) {
	data, err := os.ReadFile(c.activePath(key))
	if os.IsNotExist(err) {
		return nil, fmt.Errorf("read %q: %w", key, pg.ErrNotFound)
	}
	if err != nil {
		return nil, fmt.Errorf("read %q: %w", key, err)
	}
	return parseKVRow(key, data)
}

func (c *pvcConnector) Write(_ context.Context, key string, value json.RawMessage) error {
	path := c.activePath(key)
	data, err := wrapWithTimestamps(value, path)
	if err != nil {
		return fmt.Errorf("write %q: %w", key, err)
	}
	return atomicWrite(path, data)
}

func (c *pvcConnector) WriteConditional(_ context.Context, key string, value json.RawMessage, ifStatus string) error {
	path := c.activePath(key)

	f, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE, 0640)
	if err != nil {
		return fmt.Errorf("conditional write %q open: %w", key, err)
	}
	defer f.Close()

	if err := unix.Flock(int(f.Fd()), unix.LOCK_EX); err != nil {
		return fmt.Errorf("conditional write %q flock: %w", key, err)
	}
	defer unix.Flock(int(f.Fd()), unix.LOCK_UN) //nolint:errcheck

	info, _ := f.Stat()
	existing := make([]byte, info.Size())
	if info.Size() > 0 {
		if _, err := f.Read(existing); err != nil {
			return fmt.Errorf("conditional write %q read: %w", key, err)
		}
		var doc map[string]any
		if err := json.Unmarshal(existing, &doc); err != nil {
			return fmt.Errorf("conditional write %q unmarshal: %w", key, err)
		}
		if status, _ := doc["status"].(string); status != ifStatus {
			return fmt.Errorf("conditional write %q: %w", key, pg.ErrConditionFailed)
		}
	}

	data, err := wrapWithTimestamps(value, path)
	if err != nil {
		return fmt.Errorf("conditional write %q wrap: %w", key, err)
	}
	if err := f.Truncate(0); err != nil {
		return fmt.Errorf("conditional write %q truncate: %w", key, err)
	}
	if _, err := f.WriteAt(data, 0); err != nil {
		return fmt.Errorf("conditional write %q write: %w", key, err)
	}
	return nil
}

func (c *pvcConnector) Exists(_ context.Context, key string) (bool, error) {
	_, err := os.Stat(c.activePath(key))
	if os.IsNotExist(err) {
		return false, nil
	}
	return err == nil, err
}

func (c *pvcConnector) Delete(_ context.Context, key string) error {
	path := c.activePath(key)
	if _, err := os.Stat(path); os.IsNotExist(err) {
		return fmt.Errorf("delete %q: %w", key, pg.ErrNotFound)
	}
	if c.cfg.Partition && c.shouldArchive(path) {
		dst := filepath.Join(c.cfg.BaseDir, "archive", filepath.Base(path))
		if err := os.Rename(path, dst); err != nil {
			return fmt.Errorf("archive %q: %w", path, err)
		}
		return nil
	}
	if err := os.Remove(path); err != nil {
		return fmt.Errorf("delete %q: %w", path, err)
	}
	return nil
}

func (c *pvcConnector) shouldArchive(path string) bool {
	if len(c.cfg.ArchiveStatuses) == 0 {
		return false
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return false
	}
	var doc map[string]any
	if err := json.Unmarshal(data, &doc); err != nil {
		return false
	}
	status, _ := doc["status"].(string)
	return slices.Contains(c.cfg.ArchiveStatuses, status)
}

func (c *pvcConnector) List(_ context.Context, prefix string) ([]string, error) {
	dir := c.cfg.BaseDir
	if c.cfg.Partition {
		dir = filepath.Join(dir, "active")
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("list: %w", err)
	}
	var keys []string
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		key := strings.TrimSuffix(e.Name(), ".json")
		if strings.HasPrefix(key, prefix) {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	return keys, nil
}

func (c *pvcConnector) Query(ctx context.Context, req pg.QueryRequest) (*pg.QueryResponse, error) {
	return c.qe.query(ctx, req)
}

// ─── file helpers ────────────────────────────────────────────────────────────

// wrapWithTimestamps merges _ca/_ua timestamp fields into the JSON document.
// Preserves _ca from existing file if present.
func wrapWithTimestamps(value json.RawMessage, existingPath string) ([]byte, error) {
	now := time.Now().UTC()
	createdAt := now

	if existing, err := os.ReadFile(existingPath); err == nil {
		var doc map[string]json.RawMessage
		if json.Unmarshal(existing, &doc) == nil {
			if raw, ok := doc["_ca"]; ok {
				var t time.Time
				if json.Unmarshal(raw, &t) == nil && !t.IsZero() {
					createdAt = t
				}
			}
		}
	}

	var doc map[string]json.RawMessage
	if err := json.Unmarshal(value, &doc); err != nil {
		return nil, err
	}
	caBytes, _ := json.Marshal(createdAt)
	uaBytes, _ := json.Marshal(now)
	doc["_ca"] = caBytes
	doc["_ua"] = uaBytes
	return json.Marshal(doc)
}

// parseKVRow deserializes a stored JSON file into a pg.KVRow.
// Strips internal _ca/_ua fields from the returned Value.
func parseKVRow(key string, data []byte) (*pg.KVRow, error) {
	var doc map[string]json.RawMessage
	if err := json.Unmarshal(data, &doc); err != nil {
		return nil, fmt.Errorf("parse %q: %w", key, err)
	}

	var createdAt, updatedAt time.Time
	if raw, ok := doc["_ca"]; ok {
		_ = json.Unmarshal(raw, &createdAt)
	}
	if raw, ok := doc["_ua"]; ok {
		_ = json.Unmarshal(raw, &updatedAt)
	}
	delete(doc, "_ca")
	delete(doc, "_ua")

	value, err := json.Marshal(doc)
	if err != nil {
		return nil, err
	}
	return &pg.KVRow{Key: key, Value: value, CreatedAt: createdAt, UpdatedAt: updatedAt}, nil
}

// atomicWrite writes data to path via temp file + rename on the same filesystem.
func atomicWrite(path string, data []byte) error {
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, ".pvckv-*")
	if err != nil {
		return err
	}
	name := tmp.Name()
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		os.Remove(name)
		return err
	}
	if err := tmp.Close(); err != nil {
		os.Remove(name)
		return err
	}
	return os.Rename(name, path)
}
