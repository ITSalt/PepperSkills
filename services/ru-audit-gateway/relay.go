package main

import (
	"context"
	"crypto/sha256"
	"errors"
	"io"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

const relayBlock = 64 << 10

// A tunnel holds one retryable block in each direction. Requests may be
// replayed after an intermediary drops a response, but never re-sent upstream.
type relayTunnel struct {
	id                      string
	s                       *session
	c                       net.Conn
	g                       *Gateway
	wmu, rmu                sync.Mutex
	closed                  sync.Once
	writeOffset, readOffset int64
	lastWrite               [32]byte
	lastWriteLen            int
	lastRead                []byte
	eof                     bool
}

func (t *relayTunnel) close() {
	t.closed.Do(func() {
		t.c.Close()
		t.g.mu.Lock()
		delete(t.g.tunnels, t.id)
		t.g.mu.Unlock()
		t.g.release(t.s)
	})
}

func relayOffset(r *http.Request) (int64, error) {
	if len(r.URL.Query()) != 1 {
		return 0, fail("invalid_offset", 400)
	}
	n, err := strconv.ParseInt(r.URL.Query().Get("offset"), 10, 64)
	if err != nil || n < 0 {
		return 0, fail("invalid_offset", 400)
	}
	return n, nil
}

func (g *Gateway) relayRemote(r *http.Request) (string, error) {
	// This handler is exposed only on the separate internal listener. Nginx
	// overwrites this header; the public 8443 listener never accepts it.
	ip := r.Header.Get("X-Pepper-Client-IP")
	source, _, sourceErr := net.SplitHostPort(r.RemoteAddr)
	if sourceErr != nil || source != g.trustedRelay || g.trustedRelay == "" {
		return "", fail("untrusted_relay", 403)
	}
	if net.ParseIP(ip) == nil || len(r.Header.Values("X-Pepper-Client-IP")) != 1 {
		return "", fail("client_ip_required", 400)
	}
	return net.JoinHostPort(ip, "0"), nil
}

func (g *Gateway) serveV2(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	if r.URL.Path == "/v2/capabilities" && r.Method == "GET" {
		jsonReply(w, 200, map[string]any{"service": "pepper-ru-audit-gateway", "protocol": 2, "relay_block": relayBlock})
		return
	}
	remote, err := g.relayRemote(r)
	if err != nil {
		writeError(w, err)
		return
	}
	if r.URL.Path == "/v2/diagnostic" && r.Method == "GET" {
		jsonReply(w, 200, map[string]any{"service": "pepper-ru-audit-gateway", "protocol": 2, "relay": "trusted", "client_ip": remote})
		return
	}
	if r.URL.Path == "/v2/sessions" && r.Method == "POST" {
		var body struct {
			Target string `json:"target"`
		}
		if err := decode(w, r, &body); err != nil {
			writeError(w, err)
			return
		}
		u, err := parseTarget(body.Target)
		if err != nil {
			writeError(w, err)
			return
		}
		key := r.Header.Get("Idempotency-Key")
		if !idemPattern.MatchString(key) {
			writeError(w, fail("idempotency_key_required", 400))
			return
		}
		s, err := g.issueVersion(remote, key, u.String(), 2)
		if err != nil {
			writeError(w, err)
			return
		}
		v := g.view(s)
		v["credential"] = credential(s)
		v["limits"] = map[string]any{"download": g.cfg.Download, "upload": g.cfg.Upload, "connections": g.cfg.Connections, "lifetime_seconds": int(g.cfg.Lifetime.Seconds())}
		jsonReply(w, 201, v)
		return
	}
	auth := r.Header.Get("Authorization")
	if !strings.HasPrefix(auth, "Bearer ") {
		writeError(w, fail("unauthorized", 401))
		return
	}
	s, err := g.authenticateToken(remote, strings.TrimPrefix(auth, "Bearer "), true, false)
	if err != nil {
		writeError(w, err)
		return
	}
	if s.Version != 2 {
		writeError(w, fail("unauthorized", 401))
		return
	}
	if r.URL.Path == "/v2/sessions/current" {
		switch r.Method {
		case "GET":
			jsonReply(w, 200, g.view(s))
		case "POST":
			g.mu.Lock()
			g.stopLocked(s, "session_closed")
			g.mu.Unlock()
			jsonReply(w, 200, g.view(s))
		default:
			writeError(w, fail("method_forbidden", 405))
		}
		return
	}
	if s.Reason != "" {
		writeError(w, fail(s.Reason, 410))
		return
	}
	if r.URL.Path == "/v2/probe" || strings.HasPrefix(r.URL.Path, "/v2/registries/") {
		// Typed v1 handlers retain their SSRF protections and response limits.
		clone := r.Clone(r.Context())
		clone.URL.Path = strings.TrimPrefix(r.URL.Path, "/v2/")
		clone.URL.Path = "/v1/" + clone.URL.Path
		// Typed v1 routes share the same destination validation and metering.
		g.serveAuthenticated(w, clone, s, false, false)
		return
	}
	if r.URL.Path == "/v2/tunnels" && r.Method == "POST" {
		var body struct {
			Address string `json:"address"`
		}
		if err := decode(w, r, &body); err != nil {
			writeError(w, err)
			return
		}
		h, p, err := net.SplitHostPort(body.Address)
		if err != nil || !validateHost(h) || (p != "80" && p != "443") {
			writeError(w, fail("invalid_destination", 400))
			return
		}
		if err := g.acquire(s); err != nil {
			writeError(w, err)
			return
		}
		c, err := g.safeDial(context.WithValue(r.Context(), dialSessionKey{}, s), "tcp", body.Address)
		if err != nil {
			g.release(s)
			writeError(w, err)
			return
		}
		t := &relayTunnel{id: randomID(), s: s, c: c, g: g}
		g.mu.Lock()
		g.tunnels[t.id] = t
		g.mu.Unlock()
		go func() { <-s.Ctx.Done(); t.close() }()
		jsonReply(w, 201, map[string]any{"tunnel_id": t.id})
		return
	}
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/v2/tunnels/"), "/")
	if !strings.HasPrefix(r.URL.Path, "/v2/tunnels/") || len(parts) != 2 || len(parts[0]) != 48 {
		writeError(w, fail("not_found", 404))
		return
	}
	g.mu.Lock()
	t := g.tunnels[parts[0]]
	g.mu.Unlock()
	if t == nil || t.s != s {
		writeError(w, fail("tunnel_lost", 410))
		return
	}
	switch {
	case parts[1] == "write" && r.Method == "POST":
		offset, err := relayOffset(r)
		if err != nil {
			writeError(w, err)
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, relayBlock)
		body, err := io.ReadAll(r.Body)
		if err != nil || len(body) == 0 {
			writeError(w, fail("invalid_block", 400))
			return
		}
		t.wmu.Lock()
		defer t.wmu.Unlock()
		sum := sha256.Sum256(body)
		if offset == t.writeOffset-int64(t.lastWriteLen) && len(body) == t.lastWriteLen && sum == t.lastWrite {
			jsonReply(w, 200, map[string]any{"offset": t.writeOffset})
			return
		}
		if offset != t.writeOffset {
			writeError(w, fail("offset_conflict", 409))
			return
		}
		if err := g.charge(s, len(body), true); err != nil {
			writeError(w, err)
			return
		}
		if _, err := t.c.Write(body); err != nil {
			t.close()
			writeError(w, fail("upstream_failed", 502))
			return
		}
		t.writeOffset += int64(len(body))
		t.lastWriteLen = len(body)
		t.lastWrite = sum
		jsonReply(w, 200, map[string]any{"offset": t.writeOffset})
	case parts[1] == "read" && r.Method == "GET":
		offset, err := relayOffset(r)
		if err != nil {
			writeError(w, err)
			return
		}
		t.rmu.Lock()
		defer t.rmu.Unlock()
		if offset == t.readOffset-int64(len(t.lastRead)) && len(t.lastRead) > 0 {
			w.Header().Set("Content-Type", "application/octet-stream")
			w.Write(t.lastRead)
			return
		}
		if offset != t.readOffset {
			writeError(w, fail("offset_conflict", 409))
			return
		}
		if t.eof {
			w.Header().Set("X-Relay-EOF", "1")
			w.WriteHeader(204)
			return
		}
		buf := make([]byte, relayBlock)
		_ = t.c.SetReadDeadline(time.Now().Add(20 * time.Second))
		n, err := t.c.Read(buf)
		if n > 0 {
			if e := g.charge(s, n, false); e != nil {
				writeError(w, e)
				return
			}
			t.lastRead = buf[:n]
			t.readOffset += int64(n)
			w.Header().Set("Content-Type", "application/octet-stream")
			w.Write(t.lastRead)
			return
		}
		if errors.Is(err, io.EOF) {
			t.eof = true
			w.Header().Set("X-Relay-EOF", "1")
			w.WriteHeader(204)
			return
		}
		if nerr, ok := err.(net.Error); ok && nerr.Timeout() {
			w.WriteHeader(204)
			return
		}
		t.close()
		writeError(w, fail("upstream_failed", 502))
	case parts[1] == "close" && r.Method == "POST":
		t.close()
		jsonReply(w, 200, map[string]bool{"closed": true})
	default:
		writeError(w, fail("method_forbidden", 405))
	}
}
