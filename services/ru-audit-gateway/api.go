package main

import (
	"context"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net"
	"net/http"
	"regexp"
	"strings"
	"time"
)

var extraRoots *x509.CertPool

func registryTLS() *tls.Config { return &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: extraRoots} }

var catalog = map[string]string{
	"minjust_extremist_materials": "https://minjust.gov.ru/uploaded/files/exportfsm.csv",
	"minjust_extremist_orgs":      "https://minjust.gov.ru/ru/documents/7822/",
	"fsb_terrorist_orgs":          "http://www.fsb.ru/fsb/npd/terror.htm",
	"minjust_foreign_agents":      "https://reestrs.minjust.gov.ru/rest/registry/39b95df9-9a68-6b6d-e1e3-e6388507067e/export?",
	"minjust_undesirable_orgs":    "https://reestrs.minjust.gov.ru/rest/registry/c2d1692e-a9f6-5a79-13ee-5da5b42980df/export?",
}
var idemPattern = regexp.MustCompile(`^[a-zA-Z0-9_-]{16,128}$`)
var innPattern = regexp.MustCompile(`^(\d{10}|\d{12})$`)

func jsonReply(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func writeError(w http.ResponseWriter, e error) {
	code, status := "internal_error", 500
	var f *failure
	if errors.As(e, &f) {
		code, status = f.Code, f.Status
	}
	if h := retryHeader(e); h != "" {
		w.Header().Set("Retry-After", h)
	}
	log.Printf("event=denied reason=%s status=%d", code, status)
	jsonReply(w, status, map[string]any{"error": code})
}
func decode(w http.ResponseWriter, r *http.Request, out any) error {
	r.Body = http.MaxBytesReader(w, r.Body, 8192)
	d := json.NewDecoder(r.Body)
	d.DisallowUnknownFields()
	if d.Decode(out) != nil {
		return fail("invalid_body", 400)
	}
	if d.Decode(new(any)) != io.EOF {
		return fail("invalid_body", 400)
	}
	return nil
}
func bearer(r *http.Request, proxy bool) string {
	h := r.Header.Get("Authorization")
	if proxy {
		h = r.Header.Get("Proxy-Authorization")
	}
	if strings.HasPrefix(h, "Bearer ") {
		return strings.TrimPrefix(h, "Bearer ")
	}
	if proxy && strings.HasPrefix(h, "Basic ") {
		b, e := base64.StdEncoding.DecodeString(strings.TrimPrefix(h, "Basic "))
		if e == nil {
			return string(b)
		}
	}
	return ""
}
func (g *Gateway) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("X-Content-Type-Options", "nosniff")
	if r.URL.Path == "/healthz" && !r.URL.IsAbs() && r.Method == "GET" {
		jsonReply(w, 200, map[string]bool{"ok": true})
		return
	}
	if r.URL.Path == "/v1/sessions" && !r.URL.IsAbs() && r.Method == "POST" {
		var b struct {
			Target string `json:"target"`
		}
		if e := decode(w, r, &b); e != nil {
			writeError(w, e)
			return
		}
		u, e := parseTarget(b.Target)
		if e != nil {
			writeError(w, e)
			return
		}
		// Validate syntax and literal IP immediately; DNS is revalidated at dial time.
		if ip := net.ParseIP(u.Hostname()); ip != nil {
			ctx, cancel := context.WithTimeout(r.Context(), g.cfg.Connect)
			_, e = g.resolvePublic(ctx, u.Hostname())
			cancel()
			if e != nil {
				writeError(w, e)
				return
			}
		}
		key := r.Header.Get("Idempotency-Key")
		if !idemPattern.MatchString(key) {
			writeError(w, fail("idempotency_key_required", 400))
			return
		}
		s, e := g.issue(r.RemoteAddr, key, u.String())
		if e != nil {
			writeError(w, e)
			return
		}
		v := g.view(s)
		v["credential"] = credential(s)
		v["limits"] = map[string]any{"download": g.cfg.Download, "upload": g.cfg.Upload, "connections": g.cfg.Connections, "lifetime_seconds": int(g.cfg.Lifetime.Seconds())}
		jsonReply(w, 201, v)
		return
	}
	proxy := r.Method == "CONNECT" || r.URL.IsAbs()
	current := !proxy && r.URL.Path == "/v1/sessions/current"
	s, e := g.authenticate(r.RemoteAddr, bearer(r, proxy), current)
	if e != nil {
		if proxy && e.(*failure).Status == 401 {
			w.Header().Set("Proxy-Authenticate", `Basic realm="ru-audit"`)
			e = fail("unauthorized", 407)
		}
		writeError(w, e)
		return
	}
	if proxy {
		if r.Method == "CONNECT" {
			g.connect(w, r, s)
		} else {
			g.forward(w, r, s)
		}
		return
	}
	if current {
		switch r.Method {
		case "GET":
			jsonReply(w, 200, g.view(s))
		case "DELETE":
			g.mu.Lock()
			g.stopLocked(s, "session_closed")
			g.mu.Unlock()
			jsonReply(w, 200, g.view(s))
		default:
			writeError(w, fail("method_forbidden", 405))
		}
		return
	}
	// Bound and meter actual API response bytes too (base64 expands source bodies).
	// Status/revocation stay available after quota exhaustion.
	w = &apiWriter{ResponseWriter: w, g: g, s: s}
	if strings.HasPrefix(r.URL.Path, "/v1/registries/") && r.Method == "GET" {
		id := strings.TrimPrefix(r.URL.Path, "/v1/registries/")
		address, ok := catalog[id]
		if id == "operators" {
			inn := r.URL.Query().Get("inn")
			if !innPattern.MatchString(inn) || len(r.URL.Query()) != 1 {
				writeError(w, fail("invalid_inn", 400))
				return
			}
			address = "https://pd.rkn.gov.ru/operators-registry/operators-list/?act=search&inn=" + inn
			ok = true
		} else if r.URL.RawQuery != "" {
			writeError(w, fail("invalid_query", 400))
			return
		}
		if !ok {
			writeError(w, fail("registry_unknown", 404))
			return
		}
		select {
		case g.registrySlots <- struct{}{}:
			defer func() { <-g.registrySlots }()
		default:
			writeError(w, &failure{"registry_busy", 503, 5})
			return
		}
		_ = http.NewResponseController(w).SetWriteDeadline(time.Now().Add(g.cfg.Idle))
		raw, final, e := g.fetch(r.Context(), s, address, 20<<20)
		if e != nil {
			writeError(w, e)
			return
		}
		sum := sha256.Sum256(raw)
		jsonReply(w, 200, map[string]any{"registry": id, "source_url": address, "final_url": final, "source_sha256": hex.EncodeToString(sum[:]), "fetched_at": g.now().UTC(), "source_trust": "official", "body_base64": base64.StdEncoding.EncodeToString(raw)})
		return
	}
	if r.URL.Path == "/v1/probe" && r.Method == "POST" {
		g.probe(w, r, s)
		return
	}
	writeError(w, fail("not_found", 404))
}
func (g *Gateway) probe(w http.ResponseWriter, r *http.Request, s *session) {
	var b struct {
		Host string `json:"host"`
	}
	if e := decode(w, r, &b); e != nil {
		writeError(w, e)
		return
	}
	if e := g.acquire(s); e != nil {
		writeError(w, e)
		return
	}
	defer g.release(s)
	ctx, cancel := context.WithTimeout(r.Context(), g.cfg.Connect)
	defer cancel()
	stop := context.AfterFunc(s.Ctx, cancel)
	defer stop()
	if e := g.startConnection(s); e != nil {
		writeError(w, e)
		return
	}
	ips, e := g.resolvePublic(ctx, b.Host)
	if e != nil {
		writeError(w, e)
		return
	}
	result := map[string]any{"host": b.Host, "ips": ips, "observed_at": g.now().UTC()}
	// Pin to the exact validated address; never resolve again inside the TLS client.
	c, e := g.dial(ctx, "tcp", net.JoinHostPort(ips[0].String(), "443"))
	if e != nil {
		result["tls"] = map[string]string{"error": "connect_failed"}
		jsonReply(w, 200, result)
		return
	}
	defer c.Close()
	stopConn := context.AfterFunc(ctx, func() { c.Close() })
	defer stopConn()
	mc := &countConn{Conn: c, g: g, s: s}
	tc := tls.Client(mc, &tls.Config{ServerName: b.Host, MinVersion: tls.VersionTLS12, RootCAs: extraRoots})
	if e = tc.HandshakeContext(ctx); e != nil {
		result["tls"] = map[string]string{"error": "tls_failed"}
	} else {
		st := tc.ConnectionState()
		cert := st.PeerCertificates[0]
		result["tls"] = map[string]any{"protocol": tls.VersionName(st.Version), "not_after": cert.NotAfter, "issuer": cert.Issuer.String(), "subject": cert.Subject.String()}
	}
	jsonReply(w, 200, result)
}

type countConn struct {
	net.Conn
	g *Gateway
	s *session
}

func (c *countConn) Read(b []byte) (int, error) {
	n, e := c.Conn.Read(b)
	if n > 0 {
		if x := c.g.charge(c.s, n, false); x != nil {
			return 0, x
		}
	}
	return n, e
}
func (c *countConn) Write(b []byte) (int, error) {
	if e := c.g.charge(c.s, len(b), true); e != nil {
		return 0, e
	}
	return c.Conn.Write(b)
}

// No content buffering here; JSON encoder and the fixed registry slots bound memory.
type apiWriter struct {
	http.ResponseWriter
	g *Gateway
	s *session
}

func (w *apiWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }
func (w *apiWriter) Write(b []byte) (int, error) {
	if e := w.g.charge(w.s, len(b), false); e != nil {
		return 0, e
	}
	return w.ResponseWriter.Write(b)
}
