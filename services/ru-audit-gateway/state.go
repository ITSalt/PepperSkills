package main

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/hex"
	"errors"
	_ "github.com/mattn/go-sqlite3"
	"log"
	"net"
	"net/netip"
	"strconv"
	"strings"
	"sync"
	"time"
)

type Config struct {
	Secret                                                 []byte
	SessionsPerDay, ActivePerIP, ActiveGlobal, Connections int
	Lifetime, Idle, Connect                                time.Duration
	Download, Upload, GlobalBytes                          int64
	Rate, Burst                                            float64
	Deny                                                   []netip.Prefix
}

func defaults() Config {
	return Config{SessionsPerDay: 3, ActivePerIP: 1, ActiveGlobal: 20, Connections: 32, Lifetime: 15 * time.Minute, Idle: 60 * time.Second, Connect: 10 * time.Second, Download: 250 << 20, Upload: 10 << 20, GlobalBytes: 20 << 30, Rate: 10, Burst: 20}
}

type failure struct {
	Code   string
	Status int
	Retry  int
}

func (e *failure) Error() string         { return e.Code }
func fail(code string, status int) error { return &failure{Code: code, Status: status} }

type session struct {
	ID, IP, Target, Token, Reason string
	Version                       int
	Expires                       time.Time
	Down, Up                      int64
	Connections                   int
	Credit                        float64
	Last                          time.Time
	Ctx                           context.Context
	Cancel                        context.CancelFunc
}
type Gateway struct {
	registrySlots chan struct{}
	cfg           Config
	db            *sql.DB
	mu            sync.Mutex
	sessions      map[string]*session
	tunnels       map[string]*relayTunnel
	boot          string
	trustedRelay  string
	now           func() time.Time
	resolve       func(context.Context, string) ([]netip.Addr, error)
	dial          func(context.Context, string, string) (net.Conn, error)
	trafficSecond int64
	trafficTotal  int64
	trafficCached bool
}

func randomID() string {
	b := make([]byte, 24)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b)
}
func (g *Gateway) mac(s string) string {
	m := hmac.New(sha256.New, g.cfg.Secret)
	m.Write([]byte(s))
	return hex.EncodeToString(m.Sum(nil))
}
func ipIdentity(remote string) (string, error) {
	host, _, err := net.SplitHostPort(remote)
	if err != nil {
		return "", err
	}
	ip, err := netip.ParseAddr(host)
	if err != nil {
		return "", err
	}
	ip = ip.Unmap()
	if ip.Is6() {
		return netip.PrefixFrom(ip, 64).Masked().String(), nil
	}
	return ip.String(), nil
}
func NewGateway(path string, c Config) (*Gateway, error) {
	if len(c.Secret) < 32 {
		return nil, errors.New("HMAC secret must contain at least 32 bytes")
	}
	db, err := sql.Open("sqlite3", path+"?_journal_mode=WAL&_busy_timeout=5000&_foreign_keys=on")
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	_, err = db.Exec(`CREATE TABLE IF NOT EXISTS leases(id TEXT PRIMARY KEY,ip TEXT NOT NULL,idem TEXT NOT NULL,target TEXT NOT NULL,issued INTEGER NOT NULL,boot TEXT NOT NULL,UNIQUE(ip,idem)); CREATE INDEX IF NOT EXISTS leases_time ON leases(issued); CREATE INDEX IF NOT EXISTS leases_ip ON leases(ip,issued); CREATE TABLE IF NOT EXISTS traffic(t INTEGER PRIMARY KEY,n INTEGER NOT NULL);`)
	if err != nil {
		db.Close()
		return nil, err
	}
	d := &net.Dialer{Timeout: c.Connect}
	g := &Gateway{registrySlots: make(chan struct{}, 2), cfg: c, db: db, sessions: map[string]*session{}, tunnels: map[string]*relayTunnel{}, boot: randomID(), now: time.Now, dial: d.DialContext}
	// Adapt the standard resolver to the narrower injectable interface.
	g.resolve = func(ctx context.Context, h string) ([]netip.Addr, error) {
		return net.DefaultResolver.LookupNetIP(ctx, "ip", h)
	}
	return g, nil
}
func (g *Gateway) Close() {
	g.mu.Lock()
	defer g.mu.Unlock()
	for _, s := range g.sessions {
		g.stopLocked(s, "server_restarted")
	}
	g.db.Close()
}
func (g *Gateway) stopLocked(s *session, reason string) {
	if s.Reason == "" {
		s.Reason = reason
		s.Cancel()
		log.Printf("event=session_end reason=%s down=%d up=%d duration_s=%d", reason, s.Down, s.Up, int(g.now().Sub(s.Expires.Add(-g.cfg.Lifetime)).Seconds()))
	}
}
func (g *Gateway) purgeLocked(now time.Time) error {
	cutoff := now.Add(-48 * time.Hour).Unix()
	if _, err := g.db.Exec("DELETE FROM leases WHERE issued < ?", cutoff); err != nil {
		return err
	}
	if _, err := g.db.Exec("DELETE FROM traffic WHERE t < ?", cutoff); err != nil {
		return err
	}
	for id, s := range g.sessions {
		if !now.Before(s.Expires) {
			g.stopLocked(s, "session_expired")
		}
		if now.After(s.Expires.Add(time.Hour)) {
			delete(g.sessions, id)
		}
	}
	return nil
}

// Called under mu. The SQL rolling window has one-second resolution, so its
// cutoff cannot change within the second. Every committed charge also updates
// this total. Re-read on ANY clock change (including rollback) and after restart.
// Persistence still precedes forwarding; no quota reservation is buffered.
func (g *Gateway) trafficUsageLocked(now time.Time) (int64, error) {
	second := now.Unix()
	if !g.trafficCached || second != g.trafficSecond {
		var total int64
		if err := g.db.QueryRow("SELECT COALESCE(SUM(n),0) FROM traffic WHERE t>?", second-86400).Scan(&total); err != nil {
			g.trafficCached = false
			return 0, err
		}
		g.trafficSecond, g.trafficTotal, g.trafficCached = second, total, true
	}
	return g.trafficTotal, nil
}

func (g *Gateway) issue(remote, idem, target string) (*session, error) {
	return g.issueVersion(remote, idem, target, 1)
}
func (g *Gateway) issueVersion(remote, idem, target string, version int) (*session, error) {
	ip, err := ipIdentity(remote)
	if err != nil {
		return nil, fail("invalid_ip", 400)
	}
	key := g.mac("ip|" + ip)
	target = g.mac("target|" + target)
	g.mu.Lock()
	defer g.mu.Unlock()
	now := g.now()
	if err = g.purgeLocked(now); err != nil {
		return nil, err
	}
	var id, oldTarget, boot string
	if version == 2 {
		err = g.db.QueryRow("SELECT id,target,boot FROM leases WHERE idem=?", idem).Scan(&id, &oldTarget, &boot)
	} else {
		err = g.db.QueryRow("SELECT id,target,boot FROM leases WHERE ip=? AND idem=?", key, idem).Scan(&id, &oldTarget, &boot)
	}
	if err == nil {
		if oldTarget != target {
			return nil, fail("idempotency_conflict", 409)
		}
		s := g.sessions[id]
		if boot != g.boot || s == nil {
			return nil, fail("session_lost", 409)
		}
		if s.Version != version {
			return nil, fail("idempotency_conflict", 409)
		}
		if s.Reason != "" {
			return nil, fail(s.Reason, 410)
		}
		return s, nil
	}
	if err != sql.ErrNoRows {
		return nil, err
	}
	var count int
	var earliest sql.NullInt64
	if err = g.db.QueryRow("SELECT COUNT(*),MIN(issued) FROM leases WHERE ip=? AND issued>?", key, now.Add(-24*time.Hour).Unix()).Scan(&count, &earliest); err != nil {
		return nil, err
	}
	if count >= g.cfg.SessionsPerDay {
		return nil, &failure{"daily_quota", 429, max(1, int(earliest.Int64+86400-now.Unix()))}
	}
	active, same := 0, 0
	var sameExpiry time.Time
	for _, s := range g.sessions {
		if s.Reason == "" {
			active++
			if s.IP == key {
				same++
				if sameExpiry.IsZero() || s.Expires.Before(sameExpiry) {
					sameExpiry = s.Expires
				}
			}
		}
	}
	if same >= g.cfg.ActivePerIP {
		return nil, &failure{"active_session", 429, max(1, int(sameExpiry.Sub(now).Seconds())+1)}
	}
	if active >= g.cfg.ActiveGlobal || len(g.sessions) >= 4096 {
		return nil, &failure{"server_busy", 503, 60}
	}
	total, err := g.trafficUsageLocked(now)
	if err != nil {
		return nil, err
	}
	if total >= g.cfg.GlobalBytes {
		return nil, &failure{"server_budget", 503, 60}
	}
	id = randomID()
	ctx, cancel := context.WithCancel(context.Background())
	s := &session{ID: id, IP: key, Target: target, Token: g.mac("token|" + g.boot + "|" + id), Version: version, Expires: now.Add(g.cfg.Lifetime), Credit: g.cfg.Burst, Last: now, Ctx: ctx, Cancel: cancel}
	if _, err = g.db.Exec("INSERT INTO leases VALUES(?,?,?,?,?,?)", id, key, idem, target, now.Unix(), g.boot); err != nil {
		cancel()
		return nil, err
	}
	g.sessions[id] = s
	time.AfterFunc(g.cfg.Lifetime, func() { g.mu.Lock(); defer g.mu.Unlock(); g.stopLocked(s, "session_expired") })
	return s, nil
}
func (g *Gateway) authenticate(remote, credential string, allowStopped bool) (*session, error) {
	return g.authenticateToken(remote, credential, allowStopped, true)
}
func (g *Gateway) authenticateToken(remote, credential string, allowStopped, bindIP bool) (*session, error) {
	id, token, ok := strings.Cut(credential, ":")
	if !ok {
		return nil, fail("unauthorized", 401)
	}
	ip := ""
	if bindIP {
		var err error
		ip, err = ipIdentity(remote)
		if err != nil {
			return nil, fail("unauthorized", 401)
		}
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	s := g.sessions[id]
	if s == nil {
		return nil, fail("session_lost", 401)
	}
	if subtle.ConstantTimeCompare([]byte(token), []byte(s.Token)) != 1 || (bindIP && s.IP != g.mac("ip|"+ip)) {
		return nil, fail("unauthorized", 401)
	}
	if !g.now().Before(s.Expires) {
		g.stopLocked(s, "session_expired")
	}
	if !allowStopped && s.Reason != "" {
		return nil, fail(s.Reason, 410)
	}
	return s, nil
}
func (g *Gateway) acquire(s *session) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	now := g.now()
	if !now.Before(s.Expires) {
		g.stopLocked(s, "session_expired")
	}
	if s.Reason != "" {
		return fail(s.Reason, 410)
	}
	if s.Connections >= g.cfg.Connections {
		return fail("connection_limit", 429)
	}
	s.Connections++
	return nil
}

// Charged per DNS/connect attempt, including redirect hops and alternate A/AAAA.
func (g *Gateway) startConnection(s *session) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	now := g.now()
	if s.Reason != "" {
		return fail(s.Reason, 410)
	}
	s.Credit = min(g.cfg.Burst, s.Credit+now.Sub(s.Last).Seconds()*g.cfg.Rate)
	s.Last = now
	if s.Credit < 1 {
		return fail("connection_rate", 429)
	}
	s.Credit--
	return nil
}
func (g *Gateway) release(s *session) { g.mu.Lock(); s.Connections--; g.mu.Unlock() }
func (g *Gateway) charge(s *session, n int, upload bool) error {
	g.mu.Lock()
	defer g.mu.Unlock()
	now := g.now()
	if !now.Before(s.Expires) {
		g.stopLocked(s, "session_expired")
	}
	if s.Reason != "" {
		return fail(s.Reason, 410)
	}
	used, limit := s.Down, g.cfg.Download
	if upload {
		used, limit = s.Up, g.cfg.Upload
	}
	if int64(n) > limit-used {
		g.stopLocked(s, "traffic_limit")
		return fail("traffic_limit", 429)
	}
	total, err := g.trafficUsageLocked(now)
	if err != nil {
		g.stopLocked(s, "accounting_unavailable")
		return err
	}
	if int64(n) > g.cfg.GlobalBytes-total {
		for _, x := range g.sessions {
			g.stopLocked(x, "server_budget")
		}
		return fail("server_budget", 503)
	}
	if _, err := g.db.Exec("INSERT INTO traffic(t,n) VALUES(?,?) ON CONFLICT(t) DO UPDATE SET n=n+excluded.n", now.Unix(), n); err != nil {
		g.stopLocked(s, "accounting_unavailable")
		return err
	}
	g.trafficTotal += int64(n)
	if upload {
		s.Up += int64(n)
	} else {
		s.Down += int64(n)
	}
	// Reaching the exact limit revokes idle sibling tunnels too. Counters reserve
	// bytes before writes, so the last in-flight block can conservatively be lost.
	if s.Up >= g.cfg.Upload || s.Down >= g.cfg.Download {
		g.stopLocked(s, "traffic_limit")
	}
	if total+int64(n) >= g.cfg.GlobalBytes {
		for _, x := range g.sessions {
			g.stopLocked(x, "server_budget")
		}
	}
	return nil
}
func (g *Gateway) view(s *session) map[string]any {
	g.mu.Lock()
	defer g.mu.Unlock()
	var count int
	var earliest sql.NullInt64
	_ = g.db.QueryRow("SELECT COUNT(*),MIN(issued) FROM leases WHERE ip=? AND issued>?", s.IP, g.now().Add(-24*time.Hour).Unix()).Scan(&count, &earliest)
	return map[string]any{"launches_remaining": max(0, g.cfg.SessionsPerDay-count), "next_launch_at": time.Unix(earliest.Int64+86400, 0).UTC(), "session_id": s.ID, "expires_at": s.Expires.UTC(), "reason": s.Reason, "download_remaining": max(0, g.cfg.Download-s.Down), "upload_remaining": max(0, g.cfg.Upload-s.Up), "connections": s.Connections}
}
func credential(s *session) string { return s.ID + ":" + s.Token }
func retryHeader(e error) string {
	var f *failure
	if errors.As(e, &f) && f.Retry > 0 {
		return strconv.Itoa(f.Retry)
	}
	return ""
}
func (g *Gateway) sweep(ctx context.Context) {
	t := time.NewTicker(time.Minute)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			g.mu.Lock()
			_ = g.purgeLocked(g.now())
			g.mu.Unlock()
		}
	}
}
