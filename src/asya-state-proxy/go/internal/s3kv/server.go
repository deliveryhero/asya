package s3kv

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"strings"
	"time"
)

// NewHTTPHandler returns an http.Handler exposing the state-proxy interface.
//
//	GET    /healthz         -> 200 ok
//	GET    /keys/{key}      -> Read   (returns KVRow JSON)
//	GET    /keys/           -> List   (?prefix=)
//	PUT    /keys/{key}      -> Write  (?if_status= for conditional)
//	HEAD   /keys/{key}      -> Exists (204 | 404)
//	DELETE /keys/{key}      -> Delete
//	POST   /query           -> Query  (Mango filter)
func NewHTTPHandler(conn ServerConnector) http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})

	mux.HandleFunc("/keys/", func(w http.ResponseWriter, r *http.Request) {
		key := strings.TrimPrefix(r.URL.Path, "/keys/")
		if key == "" {
			if r.Method != http.MethodGet {
				http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
				return
			}
			handleList(w, r, conn)
			return
		}
		switch r.Method {
		case http.MethodGet:
			handleRead(w, r, conn, key)
		case http.MethodPut:
			handleWrite(w, r, conn, key)
		case http.MethodHead:
			handleExists(w, r, conn, key)
		case http.MethodDelete:
			handleDelete(w, r, conn, key)
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	})

	mux.HandleFunc("/query", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		handleQuery(w, r, conn)
	})

	return mux
}

func handleRead(w http.ResponseWriter, r *http.Request, conn ServerConnector, key string) {
	row, err := conn.Read(r.Context(), key)
	if errors.Is(err, ErrNotFound) {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(row)
}

func handleWrite(w http.ResponseWriter, r *http.Request, conn ServerConnector, key string) {
	r.Body = http.MaxBytesReader(w, r.Body, 10*1024*1024)
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "failed to read body", http.StatusBadRequest)
		return
	}
	if !json.Valid(body) {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}

	ifStatus := r.URL.Query().Get("if_status")
	if ifStatus != "" {
		err = conn.WriteConditional(r.Context(), key, body, ifStatus)
		if errors.Is(err, ErrConditionFailed) {
			http.Error(w, "condition failed: status mismatch", http.StatusConflict)
			return
		}
		if errors.Is(err, ErrNotFound) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
	} else {
		err = conn.Write(r.Context(), key, body)
	}
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func handleExists(w http.ResponseWriter, r *http.Request, conn ServerConnector, key string) {
	exists, err := conn.Exists(r.Context(), key)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if !exists {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	w.WriteHeader(http.StatusOK)
}

func handleDelete(w http.ResponseWriter, r *http.Request, conn ServerConnector, key string) {
	err := conn.Delete(r.Context(), key)
	if errors.Is(err, ErrNotFound) {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func handleList(w http.ResponseWriter, r *http.Request, conn ServerConnector) {
	prefix := r.URL.Query().Get("prefix")
	keys, err := conn.List(r.Context(), prefix)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if keys == nil {
		keys = []string{}
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"keys": keys})
}

func handleQuery(w http.ResponseWriter, r *http.Request, conn ServerConnector) {
	r.Body = http.MaxBytesReader(w, r.Body, 10*1024*1024)
	var req QueryRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}
	resp, err := conn.Query(r.Context(), req)
	if err != nil {
		slog.Error("query failed", "err", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}

// ListenUnixSocket starts an HTTP server on a Unix socket.
// Removes a stale socket file if present. Blocks until ctx is canceled.
func ListenUnixSocket(ctx context.Context, socketPath string, handler http.Handler) error {
	if err := os.Remove(socketPath); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("remove stale socket %s: %w", socketPath, err)
	}
	ln, err := net.Listen("unix", socketPath)
	if err != nil {
		return fmt.Errorf("listen unix %s: %w", socketPath, err)
	}
	defer ln.Close()

	if err := os.Chmod(socketPath, 0666); err != nil { // nosemgrep
		slog.Warn("chmod socket failed", "path", socketPath, "err", err)
	}

	srv := &http.Server{
		Handler:     handler,
		ReadTimeout: 30 * time.Second,
		IdleTimeout: 120 * time.Second,
	}

	go func() {
		<-ctx.Done()
		slog.Info("shutting down s3-kv HTTP server")
		_ = srv.Close()
	}()

	slog.Info("s3-kv state-proxy listening", "socket", socketPath)
	if err := srv.Serve(ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
		return fmt.Errorf("serve: %w", err)
	}
	return nil
}
