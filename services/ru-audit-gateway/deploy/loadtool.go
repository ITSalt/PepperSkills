// Standalone, bounded load harness. No secrets are written to stdout.
// Build with: GOOS=linux GOARCH=amd64 go build -o loadtool deploy/loadtool.go
package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/tls"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"sort"
	"strconv"
	"sync"
	"sync/atomic"
	"time"
)

func main() {
	if len(os.Args) > 1 && os.Args[1] == "fixture" {
		fixture()
		return
	}
	if len(os.Args) > 1 && os.Args[1] == "relay" {
		if err := relayLoad(); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		return
	}
	if err := load(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func fixture() {
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/octet-stream")
		w.Header().Set("Connection", "close")
		w.WriteHeader(200)
		fl := w.(http.Flusher)
		fl.Flush()
		// 8 KiB/s per socket; 640 sockets produce at most 5 MiB/s.
		b := make([]byte, 2048)
		tick := time.NewTicker(250 * time.Millisecond)
		defer tick.Stop()
		end := time.NewTimer(100 * time.Second)
		defer end.Stop()
		for {
			select {
			case <-r.Context().Done():
				return
			case <-end.C:
				return
			case <-tick.C:
				if _, e := w.Write(b); e != nil {
					return
				}
				fl.Flush()
			}
		}
	})
	s := &http.Server{Addr: ":80", Handler: h, ReadHeaderTimeout: 5 * time.Second, WriteTimeout: 110 * time.Second, MaxHeaderBytes: 8192}
	if e := s.ListenAndServe(); e != nil {
		panic(e)
	}
}
func load() error {
	addr := os.Getenv("GATEWAY_ADDR")
	if addr == "" {
		return fmt.Errorf("GATEWAY_ADDR required")
	}
	sni := os.Getenv("TLS_SERVER_NAME")
	tc := &tls.Config{MinVersion: tls.VersionTLS12, ServerName: sni, NextProtos: []string{"http/1.1"}, ClientSessionCache: tls.NewLRUClientSessionCache(1024)}
	tr := &http.Transport{TLSClientConfig: tc, MaxIdleConnsPerHost: 30}
	client := &http.Client{Transport: tr, Timeout: 15 * time.Second}
	defer tr.CloseIdleConnections()
	api := func(method, path, credential string, body any) (int, map[string]any, error) {
		b, _ := json.Marshal(body)
		r, _ := http.NewRequest(method, "https://"+addr+path, bytes.NewReader(b))
		if credential != "" {
			r.Header.Set("Authorization", "Bearer "+credential)
		}
		r.Header.Set("Idempotency-Key", fmt.Sprintf("loadtest-%d", time.Now().UnixNano()))
		r.Header.Set("Content-Type", "application/json")
		resp, e := client.Do(r)
		if e != nil {
			return 0, nil, e
		}
		defer resp.Body.Close()
		var v map[string]any
		e = json.NewDecoder(resp.Body).Decode(&v)
		return resp.StatusCode, v, e
	}
	var creds []string
	defer func() {
		for _, c := range creds {
			api("DELETE", "/v1/sessions/current", c, nil)
		}
	}()
	for i := 0; i < 20; i++ {
		code, v, e := api("POST", "/v1/sessions", "", map[string]string{"target": "http://82.202.140.54/stream"})
		if e != nil || code != 201 {
			return fmt.Errorf("issue %d status=%d error=%v", i, code, e)
		}
		creds = append(creds, v["credential"].(string))
	}
	code, v, e := api("POST", "/v1/sessions", "", map[string]string{"target": "http://82.202.140.54/stream"})
	if e != nil || code != 503 {
		return fmt.Errorf("overload status=%d error=%v", code, e)
	}
	fmt.Printf("{\"event\":\"global_limit\",\"status\":%d,\"reason\":%q}\n", code, v["error"])
	var mu sync.Mutex
	var latency []float64
	var sockets []net.Conn
	var wg sync.WaitGroup
	var received, active, peak, failed, connected atomic.Int64
	var errorsByReason sync.Map
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Second)
	defer cancel()
	start := time.Now()
	startOne := func(credential string) {
		wg.Add(1)
		go func() {
			defer wg.Done()
			t := time.Now()
			d := &tls.Dialer{NetDialer: &net.Dialer{Timeout: 10 * time.Second}, Config: tc}
			c, e := d.DialContext(ctx, "tcp", addr)
			if e != nil {
				failed.Add(1)
				errorsByReason.Store("tls_dial", true)
				return
			}
			defer c.Close()
			c.SetDeadline(time.Now().Add(95 * time.Second))
			fmt.Fprintf(c, "CONNECT 82.202.140.54:80 HTTP/1.1\r\nHost: 82.202.140.54:80\r\nProxy-Authorization: Basic %s\r\n\r\n", base64.StdEncoding.EncodeToString([]byte(credential)))
			br := bufio.NewReader(c)
			resp, e := http.ReadResponse(br, &http.Request{Method: "CONNECT"})
			if e != nil || resp.StatusCode != 200 {
				failed.Add(1)
				reason := "connect_read"
				if resp != nil {
					reason = fmt.Sprint("connect_", resp.StatusCode)
				}
				errorsByReason.Store(reason, true)
				return
			}
			mu.Lock()
			latency = append(latency, time.Since(t).Seconds()*1000)
			sockets = append(sockets, c)
			mu.Unlock()
			connected.Add(1)
			n := active.Add(1)
			for {
				p := peak.Load()
				if n <= p || peak.CompareAndSwap(p, n) {
					break
				}
			}
			defer active.Add(-1)
			fmt.Fprint(c, "GET /stream HTTP/1.1\r\nHost: fixture\r\nConnection: close\r\n\r\n")
			buf := make([]byte, 16384)
			for {
				n, e := br.Read(buf)
				received.Add(int64(n))
				if e != nil {
					return
				}
			}
		}()
	}
	// Ramp 5 -> 10 -> 20 sessions, allowing the default 10/s token refill.
	for _, p := range []struct{ lo, hi int }{{0, 5}, {5, 10}, {10, 20}} {
		for j := 0; j < 20; j++ {
			for i := p.lo; i < p.hi; i++ {
				startOne(creds[i])
			}
			time.Sleep(30 * time.Millisecond)
		}
		time.Sleep(1500 * time.Millisecond)
		for j := 20; j < 32; j++ {
			for i := p.lo; i < p.hi; i++ {
				startOne(creds[i])
			}
			time.Sleep(60 * time.Millisecond)
		}
		time.Sleep(5 * time.Second)
		fmt.Printf("{\"event\":\"ramp\",\"sessions\":%d,\"active\":%d,\"bytes\":%d,\"errors\":%d}\n", p.hi, active.Load(), received.Load(), failed.Load())
	}
	fullStart := time.Now()
	before := received.Load()
	time.Sleep(20 * time.Second)
	fullMiBs := float64(received.Load()-before) / (1 << 20) / time.Since(fullStart).Seconds()
	var statusLat []float64
	for _, c := range creds {
		t := time.Now()
		code, _, e := api("GET", "/v1/sessions/current", c, nil)
		statusLat = append(statusLat, time.Since(t).Seconds()*1000)
		if e != nil || code != 200 {
			return fmt.Errorf("status under load %d %v", code, e)
		}
	}
	revokeStart := time.Now()
	for _, c := range creds {
		code, _, e := api("DELETE", "/v1/sessions/current", c, nil)
		if e != nil || code != 200 {
			return fmt.Errorf("revoke %d %v", code, e)
		}
	}
	deadline := time.Now().Add(5 * time.Second)
	for active.Load() > 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	revokeMS := time.Since(revokeStart).Seconds() * 1000
	remaining := active.Load()
	mu.Lock()
	for _, c := range sockets {
		c.Close()
	}
	mu.Unlock()
	wg.Wait()
	sort.Float64s(latency)
	sort.Float64s(statusLat)
	p95 := func(a []float64) float64 {
		if len(a) == 0 {
			return 0
		}
		return a[int(float64(len(a)-1)*.95)]
	}
	reasons := []string{}
	errorsByReason.Range(func(k, v any) bool { reasons = append(reasons, k.(string)); return true })
	result := map[string]any{"event": "result", "duration_s": time.Since(start).Seconds(), "connected": connected.Load(), "peak": peak.Load(), "errors": failed.Load(), "error_reasons": reasons, "received_mib": float64(received.Load()) / (1 << 20), "full_load_mib_s": fullMiBs, "connect_p95_ms": p95(latency), "status_p95_ms": p95(statusLat), "revoke_all_ms": revokeMS, "remaining_after_revoke": remaining}
	json.NewEncoder(os.Stdout).Encode(result)
	if failed.Load() > 0 || peak.Load() != 640 || remaining != 0 || fullMiBs < 4 || p95(latency) > 1000 || p95(statusLat) > 250 {
		return fmt.Errorf("load gate failed")
	}
	return nil
}

// relayLoad exercises the bounded HTTPS-relay protocol on the isolated
// Docker network. The client container is the only trusted ingress for this
// fixture; production never trusts arbitrary client-supplied IP headers.
func relayLoad() error {
	addr := os.Getenv("GATEWAY_ADDR")
	if addr == "" {
		return fmt.Errorf("GATEWAY_ADDR required")
	}
	base := "http://" + addr
	tr := &http.Transport{MaxIdleConns: 700, MaxIdleConnsPerHost: 700, MaxConnsPerHost: 700}
	client := &http.Client{Transport: tr, Timeout: 30 * time.Second}
	defer tr.CloseIdleConnections()
	api := func(method, path, credential, key string, payload []byte) (int, []byte, error) {
		r, err := http.NewRequest(method, base+path, bytes.NewReader(payload))
		if err != nil {
			return 0, nil, err
		}
		r.Header.Set("X-Pepper-Client-IP", "192.0.2.40")
		if credential != "" {
			r.Header.Set("Authorization", "Bearer "+credential)
		}
		if key != "" {
			r.Header.Set("Idempotency-Key", key)
		}
		if payload != nil {
			r.Header.Set("Content-Type", "application/json")
		}
		resp, err := client.Do(r)
		if err != nil {
			return 0, nil, err
		}
		defer resp.Body.Close()
		body, err := io.ReadAll(io.LimitReader(resp.Body, 65537))
		return resp.StatusCode, body, err
	}
	type lease struct {
		Credential string `json:"credential"`
	}
	creds := make([]string, 0, 20)
	defer func() {
		for _, c := range creds {
			api("POST", "/v2/sessions/current", c, "", nil)
		}
	}()
	for i := 0; i < 20; i++ {
		code, body, err := api("POST", "/v2/sessions", "", fmt.Sprintf("%032x", i+1), []byte(`{"target":"http://82.202.140.54/stream"}`))
		if err != nil || code != 201 {
			return fmt.Errorf("relay issue %d status=%d error=%v body=%s", i, code, err, body)
		}
		var v lease
		if err := json.Unmarshal(body, &v); err != nil || v.Credential == "" {
			return fmt.Errorf("invalid relay lease %d: %v", i, err)
		}
		creds = append(creds, v.Credential)
	}
	code, _, err := api("POST", "/v2/sessions", "", fmt.Sprintf("%032x", 21), []byte(`{"target":"http://82.202.140.54/stream"}`))
	if err != nil || code != 503 {
		return fmt.Errorf("relay overload status=%d error=%v", code, err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	var wg sync.WaitGroup
	var connected, active, peak, failed, received atomic.Int64
	var mu sync.Mutex
	var openLat []float64
	startOne := func(credential string) {
		wg.Add(1)
		go func() {
			defer wg.Done()
			started := time.Now()
			code, body, err := api("POST", "/v2/tunnels", credential, "", []byte(`{"address":"82.202.140.54:80"}`))
			if err != nil || code != 201 {
				failed.Add(1)
				return
			}
			var opened struct {
				TunnelID string `json:"tunnel_id"`
			}
			if json.Unmarshal(body, &opened) != nil || opened.TunnelID == "" {
				failed.Add(1)
				return
			}
			id := opened.TunnelID
			defer api("POST", "/v2/tunnels/"+id+"/close", credential, "", nil)
			mu.Lock()
			openLat = append(openLat, time.Since(started).Seconds()*1000)
			mu.Unlock()
			connected.Add(1)
			n := active.Add(1)
			for {
				p := peak.Load()
				if n <= p || peak.CompareAndSwap(p, n) {
					break
				}
			}
			defer active.Add(-1)
			request := []byte("GET /stream HTTP/1.1\r\nHost: fixture\r\nConnection: close\r\n\r\n")
			code, body, err = api("POST", "/v2/tunnels/"+id+"/write?offset=0", credential, "", request)
			if err != nil || code != 200 {
				failed.Add(1)
				return
			}
			var offset int64
			for ctx.Err() == nil {
				code, body, err = api("GET", "/v2/tunnels/"+id+"/read?offset="+strconv.FormatInt(offset, 10), credential, "", nil)
				if err != nil {
					if ctx.Err() == nil {
						failed.Add(1)
					}
					return
				}
				if code == 204 {
					continue
				}
				if code != 200 {
					if ctx.Err() == nil {
						failed.Add(1)
					}
					return
				}
				offset += int64(len(body))
				received.Add(int64(len(body)))
			}
		}()
	}
	start := time.Now()
	for _, p := range []struct{ lo, hi int }{{0, 5}, {5, 10}, {10, 20}} {
		for j := 0; j < 20; j++ {
			for i := p.lo; i < p.hi; i++ {
				startOne(creds[i])
			}
			time.Sleep(30 * time.Millisecond)
		}
		time.Sleep(1500 * time.Millisecond)
		for j := 20; j < 32; j++ {
			for i := p.lo; i < p.hi; i++ {
				startOne(creds[i])
			}
			time.Sleep(60 * time.Millisecond)
		}
		time.Sleep(5 * time.Second)
		fmt.Printf("{\"event\":\"relay_ramp\",\"sessions\":%d,\"active\":%d,\"bytes\":%d,\"errors\":%d}\n", p.hi, active.Load(), received.Load(), failed.Load())
	}
	fullStart := time.Now()
	before := received.Load()
	time.Sleep(20 * time.Second)
	fullMiBs := float64(received.Load()-before) / (1 << 20) / time.Since(fullStart).Seconds()
	var statusLat []float64
	for _, c := range creds {
		t := time.Now()
		code, _, err := api("GET", "/v2/sessions/current", c, "", nil)
		statusLat = append(statusLat, time.Since(t).Seconds()*1000)
		if err != nil || code != 200 {
			return fmt.Errorf("relay status under load %d %v", code, err)
		}
	}
	cancel()
	revokeStart := time.Now()
	for _, c := range creds {
		code, _, err := api("POST", "/v2/sessions/current", c, "", nil)
		if err != nil || code != 200 {
			return fmt.Errorf("relay revoke %d %v", code, err)
		}
	}
	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
	}
	remaining := active.Load()
	sort.Float64s(openLat)
	sort.Float64s(statusLat)
	p95 := func(a []float64) float64 {
		if len(a) == 0 {
			return 0
		}
		return a[int(float64(len(a)-1)*.95)]
	}
	result := map[string]any{"event": "relay_result", "duration_s": time.Since(start).Seconds(), "connected": connected.Load(), "peak": peak.Load(), "errors": failed.Load(), "received_mib": float64(received.Load()) / (1 << 20), "full_load_mib_s": fullMiBs, "open_p95_ms": p95(openLat), "status_p95_ms": p95(statusLat), "revoke_all_ms": time.Since(revokeStart).Seconds() * 1000, "remaining_after_revoke": remaining}
	json.NewEncoder(os.Stdout).Encode(result)
	if failed.Load() != 0 || peak.Load() != 640 || remaining != 0 || fullMiBs < 4 || p95(openLat) > 1000 || p95(statusLat) > 250 {
		return fmt.Errorf("relay load gate failed")
	}
	return nil
}
