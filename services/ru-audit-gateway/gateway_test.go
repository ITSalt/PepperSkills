package main

import (
	"bufio"
	"context"
	"crypto/tls"
	"encoding/base64"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func testGateway(t *testing.T, change func(*Config)) *Gateway {
	t.Helper()
	c := defaults()
	c.Secret = []byte(strings.Repeat("x", 32))
	if change != nil {
		change(&c)
	}
	g, e := NewGateway(filepath.Join(t.TempDir(), "quota.sqlite"), c)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(g.Close)
	return g
}
func lease(t *testing.T, g *Gateway, key string) *session {
	t.Helper()
	s, e := g.issue("192.0.2.1:1234", key, "https://example.com")
	if e != nil {
		t.Fatal(e)
	}
	return s
}
func stop(g *Gateway, s *session) { g.mu.Lock(); g.stopLocked(s, "session_closed"); g.mu.Unlock() }
func code(t *testing.T, e error, want string) {
	t.Helper()
	if e == nil || e.Error() != want {
		t.Fatalf("want %s got %v", want, e)
	}
}
func TestQuotaIdempotencyPersistence(t *testing.T) {
	c := defaults()
	c.Secret = []byte(strings.Repeat("x", 32))
	path := filepath.Join(t.TempDir(), "quota.sqlite")
	g, e := NewGateway(path, c)
	if e != nil {
		t.Fatal(e)
	}
	s := lease(t, g, "first")
	same, e := g.issue("192.0.2.1:9876", "first", "https://example.com")
	if e != nil || same.ID != s.ID {
		t.Fatal("lost-response retry spent quota")
	}
	_, e = g.issue("192.0.2.1:1234", "second", "https://example.com")
	code(t, e, "active_session")
	_, e = g.issue("192.0.2.1:1234", "first", "https://other.com")
	code(t, e, "idempotency_conflict")
	stop(g, s)
	stop(g, lease(t, g, "second"))
	stop(g, lease(t, g, "third"))
	_, e = g.issue("192.0.2.1:1234", "fourth", "https://example.com")
	code(t, e, "daily_quota")
	g.Close()
	g, e = NewGateway(path, c)
	if e != nil {
		t.Fatal(e)
	}
	defer g.Close()
	_, e = g.issue("192.0.2.1:1234", "fourth", "https://example.com")
	code(t, e, "daily_quota")
	_, e = g.issue("192.0.2.1:1234", "first", "https://example.com")
	code(t, e, "session_lost")
	now := time.Now().Add(24*time.Hour + time.Second)
	g.now = func() time.Time { return now }
	lease(t, g, "fourth")
}
func TestParallelIssuanceAndIPv6(t *testing.T) {
	g := testGateway(t, nil)
	var wg sync.WaitGroup
	ids := make(chan string, 20)
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			s, e := g.issue("[2001:db8:1234:1::1]:1234", "same", "https://example.com")
			if e != nil {
				t.Error(e)
				return
			}
			ids <- s.ID
		}()
	}
	wg.Wait()
	close(ids)
	first := ""
	for id := range ids {
		if first != "" && first != id {
			t.Fatal("duplicate leases")
		}
		first = id
	}
	_, e := g.issue("[2001:db8:1234:1::abcd]:42", "different", "https://example.com")
	code(t, e, "active_session")
	s := g.sessions[first]
	_, e = g.authenticate("[2001:db8:1234:1::f]:80", credential(s), false)
	if e != nil {
		t.Fatal(e)
	}
	_, e = g.authenticate("[2001:db8:1234:2::f]:80", credential(s), false)
	code(t, e, "unauthorized")
}
func TestForwardedIgnoredAndOverloadDoesNotSpend(t *testing.T) {
	g := testGateway(t, func(c *Config) { c.ActiveGlobal = 1 })
	request := func(ip, key, xff string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", "/v1/sessions", strings.NewReader(`{"target":"https://example.com"}`))
		r.RemoteAddr = ip
		r.Header.Set("Idempotency-Key", key)
		r.Header.Set("X-Forwarded-For", xff)
		w := httptest.NewRecorder()
		g.ServeHTTP(w, r)
		return w
	}
	if w := request("192.0.2.1:42", "aaaaaaaaaaaaaaaa", "8.8.8.8"); w.Code != 201 {
		t.Fatal(w.Body.String())
	}
	if w := request("192.0.2.1:42", "bbbbbbbbbbbbbbbb", "1.1.1.1"); w.Code != 429 {
		t.Fatal(w.Code)
	}
	if w := request("192.0.2.2:42", "cccccccccccccccc", "1.1.1.1"); w.Code != 503 {
		t.Fatal(w.Code)
	}
	var n int
	g.db.QueryRow("SELECT COUNT(*) FROM leases").Scan(&n)
	if n != 1 {
		t.Fatal(n)
	}
}
func TestBudgetsRateAndConnectionLimits(t *testing.T) {
	g := testGateway(t, func(c *Config) { c.Download = 100; c.Upload = 30; c.Connections = 2; c.Burst = 2; c.Rate = .001 })
	s := lease(t, g, "a")
	if e := g.acquire(s); e != nil {
		t.Fatal(e)
	}
	if e := g.acquire(s); e != nil {
		t.Fatal(e)
	}
	code(t, g.acquire(s), "connection_limit")
	g.release(s)
	if e := g.startConnection(s); e != nil {
		t.Fatal(e)
	}
	if e := g.startConnection(s); e != nil {
		t.Fatal(e)
	}
	code(t, g.startConnection(s), "connection_rate")
	g.release(s)
	if e := g.charge(s, 60, false); e != nil {
		t.Fatal(e)
	}
	if e := g.charge(s, 30, false); e != nil {
		t.Fatal(e)
	}
	code(t, g.charge(s, 11, false), "traffic_limit")
	select {
	case <-s.Ctx.Done():
	default:
		t.Fatal("not cancelled")
	}
	s = lease(t, g, "b")
	code(t, g.charge(s, 31, true), "traffic_limit")
}
func TestGlobalBudgetPersistent(t *testing.T) {
	g := testGateway(t, func(c *Config) { c.GlobalBytes = 80 })
	s := lease(t, g, "a")
	if e := g.charge(s, 79, false); e != nil {
		t.Fatal(e)
	}
	code(t, g.charge(s, 2, false), "server_budget")
	var sum int
	g.db.QueryRow("SELECT SUM(n) FROM traffic").Scan(&sum)
	if sum != 79 {
		t.Fatal(sum)
	}
}
func TestAddressPolicyRebindingAndPinning(t *testing.T) {
	g := testGateway(t, func(c *Config) { c.Deny = []netip.Prefix{netip.MustParsePrefix("8.8.4.4/32")} })
	for _, ip := range []string{"127.0.0.1", "10.1.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "192.0.0.1", "192.168.0.1", "224.0.0.1", "::1", "::ffff:127.0.0.1", "64:ff9b::7f00:1", "2002:7f00::1", "fe80::1", "fc00::1", "2001:db8::1", "8.8.4.4"} {
		if g.public(netip.MustParseAddr(ip)) {
			t.Error("allowed", ip)
		}
	}
	for _, ip := range []string{"8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"} {
		if !g.public(netip.MustParseAddr(ip)) {
			t.Error("denied", ip)
		}
	}
	for _, raw := range []string{"http://127.1", "http://2130706433", "http://0x7f000001", "http://[fe80::1%25eth0]", "http://user@site.com", "https://site.com:22"} {
		if _, e := parseTarget(raw); e == nil {
			t.Error("syntax allowed", raw)
		}
	}
	calls := 0
	g.resolve = func(context.Context, string) ([]netip.Addr, error) {
		calls++
		if calls == 1 {
			return []netip.Addr{netip.MustParseAddr("8.8.8.8")}, nil
		}
		return []netip.Addr{netip.MustParseAddr("127.0.0.1")}, nil
	}
	g.dial = func(_ context.Context, _ string, addr string) (net.Conn, error) {
		if addr != "8.8.8.8:443" {
			t.Error("not pinned", addr)
		}
		a, b := net.Pipe()
		b.Close()
		return a, nil
	}
	c, e := g.safeDial(context.Background(), "tcp", "example.com:443")
	if e != nil {
		t.Fatal(e)
	}
	c.Close()
	_, e = g.safeDial(context.Background(), "tcp", "example.com:443")
	code(t, e, "destination_forbidden")
	g.resolve = func(context.Context, string) ([]netip.Addr, error) {
		return []netip.Addr{netip.MustParseAddr("8.8.8.8"), netip.MustParseAddr("10.0.0.1")}, nil
	}
	_, e = g.safeDial(context.Background(), "tcp", "example.com:80")
	code(t, e, "destination_forbidden")
}
func TestExpiryClosesContinuousTunnel(t *testing.T) {
	g := testGateway(t, func(c *Config) { c.Lifetime = 100 * time.Millisecond; c.Idle = time.Second })
	s := lease(t, g, "a")
	client, proxyClient := net.Pipe()
	up, origin := net.Pipe()
	defer client.Close()
	defer origin.Close()
	done := make(chan struct{})
	go func() { g.tunnel(s, proxyClient, proxyClient, up); close(done) }()
	go func() {
		for {
			if _, e := origin.Write([]byte("continuous")); e != nil {
				return
			}
		}
	}()
	go io.Copy(io.Discard, client)
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("active stream survived expiry")
	}
}
func TestIdleTunnelReleased(t *testing.T) {
	g := testGateway(t, func(c *Config) { c.Idle = 30 * time.Millisecond })
	s := lease(t, g, "a")
	a, b := net.Pipe()
	c, d := net.Pipe()
	defer a.Close()
	defer d.Close()
	done := make(chan struct{})
	go func() { g.tunnel(s, b, b, c); close(done) }()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("idle tunnel leaked")
	}
}
func TestHTTPProxyNoCredentialLeakAndUpgrade(t *testing.T) {
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Proxy-Authorization") != "" {
			t.Error("credential leaked")
		}
		if r.URL.Path == "/ws" {
			c, b, _ := w.(http.Hijacker).Hijack()
			defer c.Close()
			fmt.Fprint(b, "HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n")
			b.Flush()
			io.Copy(c, b)
			return
		}
		w.Header().Set("Content-Type", "text/plain")
		fmt.Fprint(w, "hello")
	}))
	defer origin.Close()
	g := testGateway(t, nil)
	g.resolve = func(context.Context, string) ([]netip.Addr, error) {
		return []netip.Addr{netip.MustParseAddr("8.8.8.8")}, nil
	}
	g.dial = func(ctx context.Context, network, address string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "tcp", strings.TrimPrefix(origin.URL, "http://"))
	}
	s, e := g.issue("127.0.0.1:1", "a", "https://example.com")
	if e != nil {
		t.Fatal(e)
	}
	proxy := httptest.NewServer(g)
	defer proxy.Close()
	for _, path := range []string{"/plain", "/ws"} {
		c, e := net.Dial("tcp", strings.TrimPrefix(proxy.URL, "http://"))
		if e != nil {
			t.Fatal(e)
		}
		c.SetDeadline(time.Now().Add(2 * time.Second))
		auth := base64.StdEncoding.EncodeToString([]byte(credential(s)))
		upgrade := ""
		if path == "/ws" {
			upgrade = "Connection: Upgrade\r\nUpgrade: websocket\r\n"
		}
		fmt.Fprintf(c, "GET http://example.com%s HTTP/1.1\r\nHost: example.com\r\nProxy-Authorization: Basic %s\r\n%s\r\n", path, auth, upgrade)
		b := bufio.NewReader(c)
		resp, e := http.ReadResponse(b, nil)
		if e != nil {
			t.Fatal(e)
		}
		if path == "/ws" {
			if resp.StatusCode != 101 {
				t.Fatal(resp.Status)
			}
			fmt.Fprint(c, "echo")
			out := make([]byte, 4)
			if _, e = io.ReadFull(b, out); e != nil || string(out) != "echo" {
				t.Fatal(string(out), e)
			}
		} else {
			out, _ := io.ReadAll(resp.Body)
			if string(out) != "hello" {
				t.Fatal(string(out))
			}
		}
		c.Close()
	}
}
func TestTypedAPIRejectsArbitraryURLAndBody(t *testing.T) {
	g := testGateway(t, nil)
	s := lease(t, g, "a")
	for _, tc := range []struct {
		method, path, body string
		status             int
	}{{"POST", "/v1/probe", `{"host":"example.com","url":"http://internal"}`, 400}, {"GET", "/v1/registries/unknown", "", 404}, {"GET", "/v1/registries/operators?inn=123&url=x", "", 400}, {"GET", "/v1/registries/minjust_extremist_materials?url=x", "", 400}} {
		r := httptest.NewRequest(tc.method, tc.path, strings.NewReader(tc.body))
		r.RemoteAddr = "192.0.2.1:1"
		r.Header.Set("Authorization", "Bearer "+credential(s))
		w := httptest.NewRecorder()
		g.ServeHTTP(w, r)
		if w.Code != tc.status {
			t.Error(tc, w.Code, w.Body.String())
		}
	}
}

func TestRegistryRedirectCannotReachPrivate(t *testing.T) {
	origin := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, "http://127.0.0.1/secret", 302) }))
	defer origin.Close()
	g := testGateway(t, nil)
	s := lease(t, g, "redirect")
	calls := 0
	g.resolve = func(context.Context, string) ([]netip.Addr, error) {
		return []netip.Addr{netip.MustParseAddr("8.8.8.8")}, nil
	}
	g.dial = func(ctx context.Context, network, address string) (net.Conn, error) {
		calls++
		return (&net.Dialer{}).DialContext(ctx, "tcp", strings.TrimPrefix(origin.URL, "http://"))
	}
	_, _, e := g.fetch(context.Background(), s, "http://example.com", 1000)
	code(t, e, "upstream_failed")
	if calls != 1 {
		t.Fatalf("private redirect dialed: %d", calls)
	}
}

func TestTLSProxyCONNECTAndRevocation(t *testing.T) {
	g := testGateway(t, nil)
	s, e := g.issue("127.0.0.1:1", "tls", "https://example.com")
	if e != nil {
		t.Fatal(e)
	}
	g.resolve = func(context.Context, string) ([]netip.Addr, error) {
		return []netip.Addr{netip.MustParseAddr("8.8.8.8")}, nil
	}
	g.dial = func(context.Context, string, string) (net.Conn, error) {
		a, b := net.Pipe()
		go func() { defer b.Close(); io.Copy(b, b) }()
		return a, nil
	}
	server := httptest.NewTLSServer(g)
	defer server.Close()
	// Trust only httptest's certificate, retaining normal TLS verification.
	cfg := server.Client().Transport.(*http.Transport).TLSClientConfig.Clone()
	c, e := tls.Dial("tcp", strings.TrimPrefix(server.URL, "https://"), cfg)
	if e != nil {
		t.Fatal(e)
	}
	defer c.Close()
	c.SetDeadline(time.Now().Add(2 * time.Second))
	fmt.Fprintf(c, "CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\nProxy-Authorization: Basic %s\r\n\r\n", base64.StdEncoding.EncodeToString([]byte(credential(s))))
	b := bufio.NewReader(c)
	resp, e := http.ReadResponse(b, nil)
	if e != nil || resp.StatusCode != 200 {
		t.Fatal(resp, e)
	}
	fmt.Fprint(c, "hello")
	out := make([]byte, 5)
	if _, e = io.ReadFull(b, out); e != nil || string(out) != "hello" {
		t.Fatal(e, string(out))
	}
	r, _ := http.NewRequest("DELETE", server.URL+"/v1/sessions/current", nil)
	r.Header.Set("Authorization", "Bearer "+credential(s))
	answer, e := server.Client().Do(r)
	if e != nil {
		t.Fatal(e)
	}
	answer.Body.Close()
	if answer.StatusCode != 200 {
		t.Fatal(answer.Status)
	}
	if _, e = b.ReadByte(); e == nil {
		t.Fatal("revoked tunnel still open")
	}
}

func TestTrafficWindowCacheDurabilityAndClock(t *testing.T) {
	c := defaults()
	c.Secret = []byte(strings.Repeat("q", 32))
	c.GlobalBytes = 100
	path := filepath.Join(t.TempDir(), "quota.sqlite")
	g, e := NewGateway(path, c)
	if e != nil {
		t.Fatal(e)
	}
	now := time.Now().Truncate(time.Second)
	g.now = func() time.Time { return now }
	s := lease(t, g, "first")
	for _, n := range []int{20, 30, 40} {
		if e := g.charge(s, n, false); e != nil {
			t.Fatal(e)
		}
	}
	used, e := g.trafficUsageLocked(now)
	if e != nil || used != 90 {
		t.Fatalf("same-second charges: %d %v", used, e)
	}
	code(t, g.charge(s, 11, false), "server_budget")
	g.Close()
	g, e = NewGateway(path, c)
	if e != nil {
		t.Fatal(e)
	}
	defer g.Close()
	g.now = func() time.Time { return now }
	used, e = g.trafficUsageLocked(now)
	if e != nil || used != 90 {
		t.Fatalf("restart: %d %v", used, e)
	}
	used, e = g.trafficUsageLocked(now.Add(24 * time.Hour))
	if e != nil || used != 0 {
		t.Fatalf("rolling boundary: %d %v", used, e)
	}
	used, e = g.trafficUsageLocked(now)
	if e != nil || used != 90 {
		t.Fatalf("clock rollback: %d %v", used, e)
	}
	s = lease(t, g, "after-restart")
	code(t, g.charge(s, 11, false), "server_budget")
	var durable int64
	if e = g.db.QueryRow("SELECT SUM(n) FROM traffic").Scan(&durable); e != nil || durable != 90 {
		t.Fatalf("durable total: %d %v", durable, e)
	}
}
