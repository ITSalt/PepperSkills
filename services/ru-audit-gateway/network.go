package main

import (
	"bufio"
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

var forbidden = func() []netip.Prefix {
	var out []netip.Prefix
	for _, s := range strings.Fields(`0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 168.63.129.16/32 169.254.0.0/16 172.16.0.0/12 192.0.0.0/24 192.0.2.0/24 192.31.196.0/24 192.52.193.0/24 192.88.99.0/24 192.175.48.0/24 192.168.0.0/16 198.18.0.0/15 198.51.100.0/24 203.0.113.0/24 224.0.0.0/3 ::/96 ::ffff:0:0/96 64:ff9b::/96 64:ff9b:1::/48 100::/64 2001::/23 2001:db8::/32 2002::/16 2620:4f:8000::/48 3fff::/20 5f00::/16 fc00::/7 fe80::/10 ff00::/8`) {
		out = append(out, netip.MustParsePrefix(s))
	}
	return out
}()

func (g *Gateway) public(ip netip.Addr) bool {
	if ip.Is4In6() {
		return false
	}
	if ip.Is6() && !netip.MustParsePrefix("2000::/3").Contains(ip) {
		return false
	}
	if !ip.IsGlobalUnicast() {
		return false
	}
	for _, p := range forbidden {
		if p.Contains(ip) {
			return false
		}
	}
	for _, p := range g.cfg.Deny {
		if p.Contains(ip) {
			return false
		}
	}
	return true
}
func validateHost(h string) bool {
	if len(h) == 0 || len(h) > 253 || strings.ContainsAny(h, "%/@\\ \t\r\n") {
		return false
	}
	if ip, err := netip.ParseAddr(h); err == nil {
		return ip.Zone() == ""
	}
	h = strings.TrimSuffix(h, ".")
	// A numeric final label denotes an ambiguous, noncanonical IP spelling.
	last := h[strings.LastIndex(h, ".")+1:]
	if _, e := strconv.ParseUint(last, 0, 64); e == nil {
		return false
	}
	if !strings.Contains(h, ".") {
		return false
	}
	for _, label := range strings.Split(h, ".") {
		if len(label) == 0 || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
			return false
		}
		for _, c := range label {
			if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '-') {
				return false
			}
		}
	}
	return true
}
func parseTarget(raw string) (*url.URL, error) {
	u, e := url.Parse(raw)
	if e != nil || u == nil || u.User != nil || u.Fragment != "" || !validateHost(u.Hostname()) || (u.Scheme != "http" && u.Scheme != "https") {
		return nil, fail("invalid_target", 400)
	}
	p := u.Port()
	if p != "" && p != "80" && p != "443" {
		return nil, fail("port_forbidden", 403)
	}
	return u, nil
}
func (g *Gateway) resolvePublic(ctx context.Context, host string) ([]netip.Addr, error) {
	if !validateHost(host) {
		return nil, fail("invalid_host", 400)
	}
	var ips []netip.Addr
	if ip, e := netip.ParseAddr(host); e == nil {
		ips = []netip.Addr{ip}
	} else {
		var err error
		ips, err = g.resolve(ctx, host)
		if err != nil {
			return nil, fail("dns_failed", 502)
		}
	}
	if len(ips) == 0 || len(ips) > 64 {
		return nil, fail("dns_failed", 502)
	}
	// Reject mixed public/private answers, not just the address selected for dial.
	for _, ip := range ips {
		if !g.public(ip) {
			return nil, fail("destination_forbidden", 403)
		}
	}
	return ips, nil
}

type dialSessionKey struct{}

func (g *Gateway) safeDial(ctx context.Context, network, address string) (net.Conn, error) {
	h, p, e := net.SplitHostPort(address)
	if e != nil {
		return nil, fail("invalid_destination", 400)
	}
	if p != "80" && p != "443" {
		return nil, fail("port_forbidden", 403)
	}
	s, _ := ctx.Value(dialSessionKey{}).(*session)
	if s != nil {
		if e := g.startConnection(s); e != nil {
			return nil, e
		}
	}
	ctx, cancel := context.WithTimeout(ctx, g.cfg.Connect)
	defer cancel()
	ips, e := g.resolvePublic(ctx, h)
	if e != nil {
		return nil, e
	}
	for i, ip := range ips {
		if i > 0 && s != nil {
			if e := g.startConnection(s); e != nil {
				return nil, e
			}
		}
		c, err := g.dial(ctx, "tcp", net.JoinHostPort(ip.String(), p))
		if err == nil {
			return &idleConn{Conn: c, idle: g.cfg.Idle}, nil
		}
	}
	return nil, fail("connect_failed", 502)
}

// Each read and write has a finite deadline. Session cancellation closes both
// sockets, even if the peer sends continuously or disappears without a FIN.
func (g *Gateway) tunnel(s *session, client net.Conn, source io.Reader, up net.Conn) {
	defer client.Close()
	defer up.Close()
	done := make(chan struct{})
	defer close(done)
	go func() {
		select {
		case <-s.Ctx.Done():
			client.Close()
			up.Close()
		case <-done:
		}
	}()
	var wg sync.WaitGroup
	wg.Add(2)
	copySide := func(dst, src net.Conn, r io.Reader, upload bool) {
		defer wg.Done()
		defer dst.Close()
		defer src.Close()
		b := make([]byte, 32*1024)
		for {
			_ = src.SetReadDeadline(time.Now().Add(g.cfg.Idle))
			n, e := r.Read(b)
			if n > 0 {
				if g.charge(s, n, upload) != nil {
					return
				}
				_ = dst.SetWriteDeadline(time.Now().Add(g.cfg.Idle))
				if _, err := dst.Write(b[:n]); err != nil {
					return
				}
			}
			if e != nil {
				return
			}
		}
	}
	go copySide(up, client, source, true)
	go copySide(client, up, up, false)
	wg.Wait()
}
func (g *Gateway) connect(w http.ResponseWriter, r *http.Request, s *session) {
	if e := g.acquire(s); e != nil {
		writeError(w, e)
		return
	}
	defer g.release(s)
	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()
	stop := context.AfterFunc(s.Ctx, cancel)
	defer stop()
	up, e := g.safeDial(context.WithValue(ctx, dialSessionKey{}, s), "tcp", r.Host)
	if e != nil {
		writeError(w, e)
		return
	}
	hj, ok := w.(http.Hijacker)
	if !ok {
		up.Close()
		writeError(w, fail("http1_required", 400))
		return
	}
	c, b, e := hj.Hijack()
	if e != nil {
		up.Close()
		return
	}
	if _, e = b.WriteString("HTTP/1.1 200 Connection Established\r\n\r\n"); e == nil {
		e = b.Flush()
	}
	if e != nil {
		c.Close()
		up.Close()
		return
	}
	g.tunnel(s, c, b, up)
}
func stripHop(h http.Header) {
	for _, v := range h.Values("Connection") {
		for _, key := range strings.Split(v, ",") {
			h.Del(strings.TrimSpace(key))
		}
	}
	for _, key := range []string{"Proxy-Authorization", "Proxy-Authenticate", "Connection", "Proxy-Connection", "Keep-Alive", "TE", "Trailer", "Transfer-Encoding", "Upgrade"} {
		h.Del(key)
	}
}

type meterReader struct {
	r      io.Reader
	g      *Gateway
	s      *session
	upload bool
}

func (m meterReader) Read(b []byte) (int, error) {
	n, e := m.r.Read(b)
	if n > 0 {
		if err := m.g.charge(m.s, n, m.upload); err != nil {
			return 0, err
		}
	}
	return n, e
}

type idleConn struct {
	net.Conn
	idle time.Duration
}

func (c *idleConn) Read(b []byte) (int, error) {
	c.Conn.SetReadDeadline(time.Now().Add(c.idle))
	return c.Conn.Read(b)
}
func (c *idleConn) Write(b []byte) (int, error) {
	c.Conn.SetWriteDeadline(time.Now().Add(c.idle))
	return c.Conn.Write(b)
}
func (g *Gateway) transport(s *session) *http.Transport {
	return &http.Transport{Proxy: nil, DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
		c, e := g.safeDial(context.WithValue(ctx, dialSessionKey{}, s), network, address)
		if e != nil {
			return nil, e
		}
		return &countConn{Conn: c, g: g, s: s}, nil
	}, DisableKeepAlives: true, TLSHandshakeTimeout: g.cfg.Connect, ResponseHeaderTimeout: g.cfg.Connect, MaxResponseHeaderBytes: 32768, TLSClientConfig: registryTLS()}
}
func (g *Gateway) forward(w http.ResponseWriter, r *http.Request, s *session) {
	if r.URL.Scheme != "http" {
		writeError(w, fail("use_connect_for_https", 400))
		return
	}
	if _, e := parseTarget(r.URL.String()); e != nil {
		writeError(w, e)
		return
	}
	if r.Method == "CONNECT" || r.Method == "TRACE" {
		writeError(w, fail("method_forbidden", 405))
		return
	}
	if e := g.acquire(s); e != nil {
		writeError(w, e)
		return
	}
	defer g.release(s)
	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()
	stop := context.AfterFunc(s.Ctx, cancel)
	defer stop()
	req := r.Clone(ctx)
	req.RequestURI = ""
	req.Host = req.URL.Host
	req.Header = r.Header.Clone()
	upgrade := r.Header.Get("Upgrade")
	if upgrade != "" && (!strings.EqualFold(upgrade, "websocket") || r.Method != "GET") {
		writeError(w, fail("upgrade_forbidden", 400))
		return
	}
	stripHop(req.Header)
	if upgrade != "" {
		req.Header.Set("Connection", "Upgrade")
		req.Header.Set("Upgrade", "websocket")
	}
	req.Body = r.Body
	defer r.Body.Close()
	tr := g.transport(s)
	defer tr.CloseIdleConnections()
	resp, e := tr.RoundTrip(req)
	if e != nil {
		writeError(w, fail("upstream_failed", 502))
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusSwitchingProtocols {
		rw, ok := resp.Body.(io.ReadWriteCloser)
		if !ok || upgrade == "" {
			writeError(w, fail("invalid_upgrade", 502))
			return
		}
		c, b, e := w.(http.Hijacker).Hijack()
		if e != nil {
			return
		}
		stripHop(resp.Header)
		resp.Header.Set("Connection", "Upgrade")
		resp.Header.Set("Upgrade", "websocket")
		_, e = b.WriteString("HTTP/1.1 101 Switching Protocols\r\n")
		if e == nil {
			e = resp.Header.Write(b)
		}
		if e == nil {
			_, e = b.WriteString("\r\n")
		}
		if e == nil {
			e = b.Flush()
		}
		if e != nil {
			c.Close()
			return
		}
		// Upstream socket is already metered by transport; this handoff must not charge twice.
		g.upgradedTunnel(s, c, b, rw)
		return
	}
	stripHop(resp.Header)
	for k, v := range resp.Header {
		w.Header()[k] = v
	}
	w.WriteHeader(resp.StatusCode)
	b := make([]byte, 32*1024)
	rc := http.NewResponseController(w)
	for {
		n, err := resp.Body.Read(b)
		if n > 0 {
			_ = rc.SetWriteDeadline(time.Now().Add(g.cfg.Idle))
			if _, e = w.Write(b[:n]); e != nil {
				return
			}
			_ = rc.Flush()
		}
		if err != nil {
			return
		}
	}
}

// Session-bound, redirect-validating requests used only by typed APIs.
func (g *Gateway) fetch(ctx context.Context, s *session, address string, maxBytes int64) ([]byte, string, error) {
	if e := g.acquire(s); e != nil {
		return nil, "", e
	}
	defer g.release(s)
	ctx, cancel := context.WithTimeout(ctx, 40*time.Second)
	defer cancel()
	stop := context.AfterFunc(s.Ctx, cancel)
	defer stop()
	tr := g.transport(s)
	defer tr.CloseIdleConnections()
	c := &http.Client{Transport: tr, CheckRedirect: func(r *http.Request, via []*http.Request) error {
		if len(via) >= 5 {
			return errors.New("redirect_limit")
		}
		_, e := parseTarget(r.URL.String())
		return e
	}}
	req, e := http.NewRequestWithContext(ctx, "GET", address, nil)
	if e != nil {
		return nil, "", e
	}
	req.Header.Set("User-Agent", "Pepper-RU-Audit/2.3")
	resp, e := c.Do(req)
	if e != nil {
		return nil, "", fail("upstream_failed", 502)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, "", fail("upstream_status_"+strconv.Itoa(resp.StatusCode), 502)
	}
	b, e := io.ReadAll(io.LimitReader(resp.Body, maxBytes+1))
	if e != nil {
		return nil, "", e
	}
	if int64(len(b)) > maxBytes {
		return nil, "", fail("response_too_large", 502)
	}
	return b, resp.Request.URL.String(), nil
}

// buffer type retained explicitly in the CONNECT handoff to preserve bytes
// already read by net/http (e.g. a pipelined TLS ClientHello).
var _ io.Reader = (*bufio.ReadWriter)(nil)

func (g *Gateway) upgradedTunnel(s *session, client net.Conn, source io.Reader, up io.ReadWriteCloser) {
	defer client.Close()
	defer up.Close()
	stop := context.AfterFunc(s.Ctx, func() { client.Close(); up.Close() })
	defer stop()
	done := make(chan struct{}, 2)
	go func() {
		defer func() { client.Close(); up.Close(); done <- struct{}{} }()
		b := make([]byte, 32768)
		for {
			client.SetReadDeadline(time.Now().Add(g.cfg.Idle))
			n, e := source.Read(b)
			if n > 0 {
				if _, x := up.Write(b[:n]); x != nil {
					return
				}
			}
			if e != nil {
				return
			}
		}
	}()
	go func() {
		defer func() { client.Close(); up.Close(); done <- struct{}{} }()
		b := make([]byte, 32768)
		for {
			n, e := up.Read(b)
			if n > 0 {
				client.SetWriteDeadline(time.Now().Add(g.cfg.Idle))
				if _, x := client.Write(b[:n]); x != nil {
					return
				}
			}
			if e != nil {
				return
			}
		}
	}()
	<-done
	<-done
}
