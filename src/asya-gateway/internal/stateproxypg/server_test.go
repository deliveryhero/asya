package stateproxypg

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func testHTTPServer(t *testing.T) *httptest.Server {
	t.Helper()
	dbURL := os.Getenv("STATEPROXY_PG_TEST_URL")
	if dbURL == "" {
		t.Skip("STATEPROXY_PG_TEST_URL not set")
	}
	pool := testPool(t)
	conn := NewConnector(pool)
	handler := NewHTTPHandler(conn)
	return httptest.NewServer(handler)
}

func TestHTTPHandler_HealthCheck(t *testing.T) {
	dbURL := os.Getenv("STATEPROXY_PG_TEST_URL")
	if dbURL == "" {
		t.Skip("STATEPROXY_PG_TEST_URL not set")
	}
	srv := testHTTPServer(t)
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/healthz")
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusOK, resp.StatusCode)
}

func TestHTTPHandler_PutAndGet(t *testing.T) {
	srv := testHTTPServer(t)
	defer srv.Close()

	// PUT
	body := `{"status":"pending","actor":"echo"}`
	req, _ := http.NewRequest(http.MethodPut, srv.URL+"/keys/msg/http-1", strings.NewReader(body))
	resp, err := http.DefaultClient.Do(req)
	require.NoError(t, err)
	resp.Body.Close()
	assert.Equal(t, http.StatusNoContent, resp.StatusCode)

	// GET
	resp, err = http.Get(srv.URL + "/keys/msg/http-1")
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusOK, resp.StatusCode)

	var row KVRow
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&row))
	assert.Equal(t, "msg/http-1", row.Key)
	assert.JSONEq(t, body, string(row.Value))
}

func TestHTTPHandler_HeadExists(t *testing.T) {
	srv := testHTTPServer(t)
	defer srv.Close()

	// Write first
	req, _ := http.NewRequest(http.MethodPut, srv.URL+"/keys/msg/head-1", strings.NewReader(`{"a":1}`))
	resp, _ := http.DefaultClient.Do(req)
	resp.Body.Close()

	// HEAD existing
	req, _ = http.NewRequest(http.MethodHead, srv.URL+"/keys/msg/head-1", nil)
	resp, err := http.DefaultClient.Do(req)
	require.NoError(t, err)
	resp.Body.Close()
	assert.Equal(t, http.StatusOK, resp.StatusCode)

	// HEAD non-existing
	req, _ = http.NewRequest(http.MethodHead, srv.URL+"/keys/msg/head-nope", nil)
	resp, err = http.DefaultClient.Do(req)
	require.NoError(t, err)
	resp.Body.Close()
	assert.Equal(t, http.StatusNotFound, resp.StatusCode)
}

func TestHTTPHandler_DeleteNotFound(t *testing.T) {
	srv := testHTTPServer(t)
	defer srv.Close()

	req, _ := http.NewRequest(http.MethodDelete, srv.URL+"/keys/msg/nope", nil)
	resp, err := http.DefaultClient.Do(req)
	require.NoError(t, err)
	resp.Body.Close()
	assert.Equal(t, http.StatusNotFound, resp.StatusCode)
}

func TestHTTPHandler_ListByPrefix(t *testing.T) {
	srv := testHTTPServer(t)
	defer srv.Close()

	// Write a few keys
	for _, k := range []string{"msg/list-1", "msg/list-2", "other/x"} {
		req, _ := http.NewRequest(http.MethodPut, srv.URL+"/keys/"+k, strings.NewReader(`{"v":1}`))
		resp, _ := http.DefaultClient.Do(req)
		resp.Body.Close()
	}

	resp, err := http.Get(srv.URL + "/keys/?prefix=msg/list-")
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusOK, resp.StatusCode)

	var result map[string][]string
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&result))
	assert.Len(t, result["keys"], 2)
}

func TestHTTPHandler_QueryEndpoint(t *testing.T) {
	srv := testHTTPServer(t)
	defer srv.Close()

	// Write
	req, _ := http.NewRequest(http.MethodPut, srv.URL+"/keys/msg/q-1",
		strings.NewReader(`{"status":"running","actor":"train"}`))
	resp, _ := http.DefaultClient.Do(req)
	resp.Body.Close()

	// Query
	qBody := `{"prefix":"msg/","filter":{"status":"running"},"limit":10}`
	resp, err := http.Post(srv.URL+"/query", "application/json", strings.NewReader(qBody))
	require.NoError(t, err)
	defer resp.Body.Close()
	assert.Equal(t, http.StatusOK, resp.StatusCode)

	var qResp QueryResponse
	require.NoError(t, json.NewDecoder(resp.Body).Decode(&qResp))
	assert.GreaterOrEqual(t, qResp.Total, 1)
}

func TestHTTPHandler_PutInvalidJSON(t *testing.T) {
	srv := testHTTPServer(t)
	defer srv.Close()

	req, _ := http.NewRequest(http.MethodPut, srv.URL+"/keys/msg/bad", strings.NewReader("not json"))
	resp, err := http.DefaultClient.Do(req)
	require.NoError(t, err)
	resp.Body.Close()
	assert.Equal(t, http.StatusBadRequest, resp.StatusCode)
}

func TestHTTPHandler_GetNotFound(t *testing.T) {
	srv := testHTTPServer(t)
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/keys/msg/nonexistent")
	require.NoError(t, err)
	resp.Body.Close()
	assert.Equal(t, http.StatusNotFound, resp.StatusCode)
}
