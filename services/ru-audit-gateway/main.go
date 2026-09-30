package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"io"
	"log"
	"net"
	"net/http"
	"net/netip"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"time"
)

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}
func integer(k string, d int64) int64 {
	v := env(k, strconv.FormatInt(d, 10))
	n, e := strconv.ParseInt(v, 10, 64)
	if e != nil || n <= 0 {
		log.Fatalf("invalid configuration: %s", k)
	}
	return n
}
func main() {
	log.SetFlags(log.LstdFlags | log.LUTC)
	cfg := defaults()
	secret, e := os.ReadFile(env("HMAC_SECRET_FILE", "/run/secrets/hmac"))
	if e != nil {
		log.Fatal("HMAC_SECRET_FILE is required")
	}
	cfg.Secret = []byte(strings.TrimSpace(string(secret)))
	cfg.SessionsPerDay = int(integer("SESSIONS_PER_DAY", 3))
	cfg.ActivePerIP = int(integer("ACTIVE_PER_IP", 1))
	cfg.ActiveGlobal = int(integer("ACTIVE_GLOBAL", 20))
	cfg.Connections = int(integer("CONNECTIONS_PER_SESSION", 32))
	cfg.Lifetime = time.Duration(integer("SESSION_SECONDS", 900)) * time.Second
	cfg.Idle = time.Duration(integer("IDLE_SECONDS", 60)) * time.Second
	cfg.Connect = time.Duration(integer("CONNECT_SECONDS", 10)) * time.Second
	cfg.Download = integer("DOWNLOAD_BYTES", 250<<20)
	cfg.Upload = integer("UPLOAD_BYTES", 10<<20)
	cfg.GlobalBytes = integer("GLOBAL_BYTES_24H", 20<<30)
	cfg.Rate = float64(integer("CONNECTION_RATE", 10))
	cfg.Burst = float64(integer("CONNECTION_BURST", 20))
	// Operator MUST enumerate the public gateway and infrastructure addresses.
	deny := os.Getenv("DENY_CIDRS")
	if deny == "" {
		log.Fatal("DENY_CIDRS must include gateway public and infrastructure addresses")
	}
	for _, s := range strings.Split(deny, ",") {
		p, e := netip.ParsePrefix(strings.TrimSpace(s))
		if e != nil {
			log.Fatal("invalid DENY_CIDRS")
		}
		cfg.Deny = append(cfg.Deny, p)
	}
	if ca := os.Getenv("EXTRA_CA_FILE"); ca != "" {
		extraRoots, e = x509.SystemCertPool()
		if e != nil {
			log.Fatal("system CA unavailable")
		}
		pem, e := os.ReadFile(ca)
		if e != nil || !extraRoots.AppendCertsFromPEM(pem) {
			log.Fatal("invalid EXTRA_CA_FILE")
		}
	}
	g, e := NewGateway(env("DATABASE_PATH", "/data/gateway.sqlite"), cfg)
	if e != nil {
		log.Fatal("database initialization failed")
	}
	g.trustedRelay = os.Getenv("TRUSTED_V2_PROXY_IP")
	defer g.Close()
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()
	go g.sweep(ctx)
	var inbound atomic.Int64
	server := &http.Server{ErrorLog: log.New(io.Discard, "", 0), ConnState: func(c net.Conn, s http.ConnState) {
		switch s {
		case http.StateNew:
			if inbound.Add(1) > 1024 {
				c.Close()
			}
		case http.StateClosed, http.StateHijacked:
			inbound.Add(-1)
		}
	}, Addr: env("LISTEN_ADDR", ":8443"), Handler: g, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: cfg.Idle, IdleTimeout: cfg.Idle, MaxHeaderBytes: 16 << 10, TLSConfig: &tls.Config{MinVersion: tls.VersionTLS12, NextProtos: []string{"http/1.1"}}, TLSNextProto: map[string]func(*http.Server, *tls.Conn, http.Handler){}}
	internal := &http.Server{Addr: env("INTERNAL_LISTEN_ADDR", ":8080"), Handler: http.HandlerFunc(g.serveV2), ReadHeaderTimeout: 5 * time.Second, IdleTimeout: cfg.Idle, MaxHeaderBytes: 16 << 10}
	go func() {
		if e := internal.ListenAndServe(); e != nil && e != http.ErrServerClosed {
			log.Fatalf("internal listener failed: %v", e)
		}
	}()
	go func() {
		<-ctx.Done()
		g.mu.Lock()
		for _, s := range g.sessions {
			g.stopLocked(s, "server_shutdown")
		}
		g.mu.Unlock()
		c, stop := context.WithTimeout(context.Background(), 5*time.Second)
		defer stop()
		server.Shutdown(c)
		internal.Shutdown(c)
	}()
	// Only startup configuration is logged. No HTTP bodies, URLs or credentials.
	b, _ := json.Marshal(map[string]any{"event": "gateway_start", "active_limit": cfg.ActiveGlobal})
	log.Print(string(b))
	if e = server.ListenAndServeTLS(env("TLS_CERT_FILE", "/run/secrets/tls.crt"), env("TLS_KEY_FILE", "/run/secrets/tls.key")); e != nil && e != http.ErrServerClosed {
		log.Fatal("TLS listener failed")
	}
}
