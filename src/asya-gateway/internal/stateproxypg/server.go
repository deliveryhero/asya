package stateproxypg

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
)

// NewHTTPHandler returns an http.Handler that routes to the connector.
//
//	GET    /healthz        -> health check
//	GET    /keys/{key}     -> Read (when path has key) or List (when ?prefix=)
//	PUT    /keys/{key}     -> Write
//	HEAD   /keys/{key}     -> Exists
//	DELETE /keys/{key}     -> Delete
//	GET    /keys/          -> List (with ?prefix=)
//	POST   /query          -> Query
func NewHTTPHandler(conn *Connector) http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})

	mux.HandleFunc("/keys/", func(w http.ResponseWriter, r *http.Request) {
		key := strings.TrimPrefix(r.URL.Path, "/keys/")

		if key == "" {
			// List by prefix
			if r.Method != http.MethodGet {
				http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
				return
			}
			prefix := r.URL.Query().Get("prefix")
			handleList(w, r, conn, prefix)
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

func handleRead(w http.ResponseWriter, r *http.Request, conn *Connector, key string) {
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

func handleWrite(w http.ResponseWriter, r *http.Request, conn *Connector, key string) {
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
	} else {
		err = conn.Write(r.Context(), key, body)
	}
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func handleExists(w http.ResponseWriter, r *http.Request, conn *Connector, key string) {
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

func handleDelete(w http.ResponseWriter, r *http.Request, conn *Connector, key string) {
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

func handleList(w http.ResponseWriter, r *http.Request, conn *Connector, prefix string) {
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

func handleQuery(w http.ResponseWriter, r *http.Request, conn *Connector) {
	r.Body = http.MaxBytesReader(w, r.Body, 10*1024*1024)
	var req QueryRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}
	resp, err := conn.Query(r.Context(), req)
	if errors.Is(err, ErrInvalidFieldName) {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	if err != nil {
		slog.Error("Query failed", "error", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}

// ListenUnixSocket starts an HTTP server on the given Unix socket path.
// Removes stale socket file if present. Blocks until ctx is canceled.
func ListenUnixSocket(ctx context.Context, socketPath string, handler http.Handler) error {
	// Remove stale socket file if present
	if err := os.Remove(socketPath); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("remove stale socket %s: %w", socketPath, err)
	}

	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		return fmt.Errorf("listen unix %s: %w", socketPath, err)
	}
	defer func() {
		if err := listener.Close(); err != nil {
			slog.Warn("Failed to close listener", "error", err)
		}
	}()

	// Restrict socket to owner; containers in the same pod share the same
	// user namespace, so 0600 is sufficient for inter-container access.
	if err := os.Chmod(socketPath, 0600); err != nil { // nosemgrep
		slog.Warn("Failed to chmod socket", "path", socketPath, "error", err)
	}

	server := &http.Server{Handler: handler}

	// Graceful shutdown when context is canceled
	go func() {
		<-ctx.Done()
		slog.Info("Shutting down state-proxy-pg HTTP server")
		_ = server.Close()
	}()

	slog.Info("State-proxy-pg listening", "socket", socketPath)
	if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
		return fmt.Errorf("serve: %w", err)
	}
	return nil
}
