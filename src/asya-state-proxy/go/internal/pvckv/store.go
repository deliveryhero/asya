// Package pvckv provides an in-memory and PVC-backed key-value store that
// implements pg.ServerConnector, reusing pg.NewHTTPHandler without adapters.
package pvckv

import (
	"fmt"

	"github.com/deliveryhero/asya/asya-state-proxy-go/internal/pg"
)

// Config controls which backend and options are used.
type Config struct {
	Mode            string   // "inmem" | "pvc"
	BaseDir         string   // PVC_KV_BASE_DIR, required for pvc mode
	Partition       bool     // PVC_KV_PARTITION — enables active/ + archive/ subdirs
	ArchiveStatuses []string // statuses moved to archive/ on delete
}

// NewConnector creates a pg.ServerConnector backed by local storage.
// The returned value can be passed directly to pg.NewHTTPHandler.
func NewConnector(cfg Config) (pg.ServerConnector, error) {
	switch cfg.Mode {
	case "inmem":
		return newInMemConnector(), nil
	case "pvc":
		return newPVCConnector(cfg)
	default:
		return nil, fmt.Errorf("unknown PVC_KV_MODE %q: expected inmem or pvc", cfg.Mode)
	}
}
