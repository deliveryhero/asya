package toolstore

import (
	"context"
	"time"

	"github.com/deliveryhero/asya/asya-gateway/internal/watcher"
)

// Watch polls dir every pollInterval and reloads the registry when file contents change.
// It logs errors but never stops -- the previous cache is preserved on load failure.
// Call with go Watch(...) to run in the background.
func Watch(ctx context.Context, dir string, r *Registry, pollInterval time.Duration) {
	watcher.Watch(ctx, dir, pollInterval, func(d string) error {
		return r.LoadFromDir(d)
	})
}
