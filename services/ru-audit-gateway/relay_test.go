package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net"
	"net/http/httptest"
	"net/netip"
	"strings"
	"testing"
)

func TestRelayRetryAndChangingClientIP(t *testing.T) {
	g := testGateway(t, nil)
	g.trustedRelay = "192.0.2.1"
	g.resolve = func(context.Context, string) ([]netip.Addr, error) {
		return []netip.Addr{netip.MustParseAddr("8.8.8.8")}, nil
	}
	received := make(chan string, 2)
	g.dial = func(context.Context, string, string) (net.Conn, error) {
		client, origin := net.Pipe()
		go func() {
			defer origin.Close()
			buf := make([]byte, 128)
			n, _ := origin.Read(buf)
			received <- string(buf[:n])
			origin.Write([]byte("pong"))
		}()
		return client, nil
	}
	call := func(method, path, ip, token string, body []byte) *httptest.ResponseRecorder {
		r := httptest.NewRequest(method, path, bytes.NewReader(body))
		r.Header.Set("X-Pepper-Client-IP", ip)
		if token != "" {
			r.Header.Set("Authorization", "Bearer "+token)
		}
		if path == "/v2/sessions" {
			r.Header.Set("Idempotency-Key", strings.Repeat("a", 32))
		}
		w := httptest.NewRecorder()
		g.serveV2(w, r)
		return w
	}
	if diagnostic := call("GET", "/v2/diagnostic", "1.1.1.1", "", nil); diagnostic.Code != 200 || !strings.Contains(diagnostic.Body.String(), `"relay":"trusted"`) {
		t.Fatal("trusted ingress diagnostic failed", diagnostic.Code, diagnostic.Body.String())
	}
	start := call("POST", "/v2/sessions", "1.1.1.1", "", []byte(`{"target":"https://example.com"}`))
	if start.Code != 201 {
		t.Fatal(start.Body.String())
	}
	var lease map[string]any
	json.Unmarshal(start.Body.Bytes(), &lease)
	token := lease["credential"].(string)
	retry := call("POST", "/v2/sessions", "2.2.2.2", "", []byte(`{"target":"https://example.com"}`))
	if retry.Code != 201 {
		t.Fatal(retry.Body.String())
	}
	var again map[string]any
	json.Unmarshal(retry.Body.Bytes(), &again)
	if again["session_id"] != lease["session_id"] {
		t.Fatal("retry created another lease")
	}
	if w := call("GET", "/v2/sessions/current", "2.2.2.2", token, nil); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	open := call("POST", "/v2/tunnels", "2.2.2.2", token, []byte(`{"address":"example.com:80"}`))
	if open.Code != 201 {
		t.Fatal(open.Body.String())
	}
	var opened map[string]string
	json.Unmarshal(open.Body.Bytes(), &opened)
	id := opened["tunnel_id"]
	write := "/v2/tunnels/" + id + "/write?offset=0"
	for i := 0; i < 2; i++ {
		if w := call("POST", write, "2.2.2.2", token, []byte("ping")); w.Code != 200 {
			t.Fatal(w.Body.String())
		}
	}
	if got := <-received; got != "ping" {
		t.Fatal(got)
	}
	read := "/v2/tunnels/" + id + "/read?offset=0"
	for i := 0; i < 2; i++ {
		w := call("GET", read, "1.1.1.1", token, nil)
		if w.Code != 200 || w.Body.String() != "pong" {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	if w := call("POST", "/v2/tunnels/"+id+"/close", "1.1.1.1", token, nil); w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	var count int
	g.db.QueryRow("SELECT COUNT(*) FROM leases").Scan(&count)
	if count != 1 {
		t.Fatal("retry spent quota", count)
	}
	select {
	case duplicate := <-received:
		t.Fatal("duplicate upstream write", duplicate)
	default:
	}
}

func TestPublicV1DoesNotTrustClientHeaderOrExposeV2(t *testing.T) {
	g := testGateway(t, nil)
	g.trustedRelay = "192.0.2.1"
	r := httptest.NewRequest("GET", "/v2/capabilities", nil)
	r.Header.Set("X-Pepper-Client-IP", "1.1.1.1")
	w := httptest.NewRecorder()
	g.ServeHTTP(w, r)
	if w.Code == 200 {
		t.Fatal("public v1 listener exposed v2")
	}
	r = httptest.NewRequest("POST", "/v2/sessions", strings.NewReader(`{"target":"https://example.com"}`))
	r.RemoteAddr = "192.0.2.99:1234"
	r.Header.Set("X-Pepper-Client-IP", "1.1.1.1")
	r.Header.Set("Idempotency-Key", strings.Repeat("z", 32))
	w = httptest.NewRecorder()
	g.serveV2(w, r)
	if w.Code != 403 {
		t.Fatal("untrusted source spoofed client IP", w.Code)
	}
}
