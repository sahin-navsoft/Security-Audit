#!/usr/bin/env python3
"""Passive live-site health & config checker.

Read-only. For each URL it performs ONE ordinary HTTPS GET (following
redirects) and inspects what the server volunteers: the TLS certificate,
response security headers, Set-Cookie flags, and the HTTP->HTTPS redirect.

It sends no payloads, does no fuzzing, tries no credentials, and probes no
paths beyond the URL you give it. It is the live-site equivalent of reading a
page's response headers in your browser's dev tools. Only run it against sites
you are authorized to test.

Usage:
    python3 check_site.py https://example.com [https://another.example ...]
    python3 check_site.py --json-out report.json https://example.com

Exit code is 0 unless a URL could not be reached at all.
"""
import argparse
import datetime as _dt
import http.cookies
import json
import socket
import ssl
import sys
import urllib.error
import urllib.request

TIMEOUT = 15
UA = "live-site-audit/1.0 (passive header & TLS check)"

# Response headers we expect a hardened site to send, with why they matter.
SECURITY_HEADERS = {
    "strict-transport-security": (
        "high",
        "No HSTS header, so a browser can be downgraded to plain HTTP on the "
        "first visit or by an active network attacker.",
        "Add 'Strict-Transport-Security: max-age=31536000; includeSubDomains'.",
    ),
    "content-security-policy": (
        "high",
        "No Content-Security-Policy, so an injected script has nothing stopping "
        "it from running or exfiltrating data.",
        "Add a Content-Security-Policy that restricts script, style and connect sources.",
    ),
    "x-content-type-options": (
        "medium",
        "No X-Content-Type-Options, so browsers may MIME-sniff a response and "
        "treat an upload as executable script.",
        "Add 'X-Content-Type-Options: nosniff'.",
    ),
    "x-frame-options": (
        "medium",
        "No framing protection, so the page can be embedded in an attacker's "
        "iframe for click-jacking.",
        "Add 'X-Frame-Options: DENY' or a CSP frame-ancestors directive.",
    ),
    "referrer-policy": (
        "low",
        "No Referrer-Policy, so full URLs (which may carry tokens) can leak to "
        "third-party sites via the Referer header.",
        "Add 'Referrer-Policy: strict-origin-when-cross-origin'.",
    ),
    "permissions-policy": (
        "low",
        "No Permissions-Policy, so embedded content can request camera, mic or "
        "geolocation without an explicit allow-list.",
        "Add a Permissions-Policy that disables features you do not use.",
    ),
}

# Headers that leak stack details; informational only.
DISCLOSURE_HEADERS = ("server", "x-powered-by", "x-aspnet-version", "x-generator")


def _finding(sev, title, what, why, fix):
    return {"severity": sev, "title": title, "what": what, "why": why, "fix": fix}


def check_tls(host, port=443):
    """Return (findings, info) about the certificate and protocol. Passive: one handshake."""
    findings, info = [], {}
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                info["protocol"] = ssock.version()
                info["cipher"] = ssock.cipher()[0] if ssock.cipher() else None
    except ssl.SSLCertVerificationError as e:
        findings.append(_finding(
            "high", "TLS certificate does not validate",
            f"The certificate for {host} failed verification: {e.verify_message}.",
            "Browsers show a full-page security warning, and the connection is not trustworthy.",
            "Install a valid certificate chain from a trusted CA that matches the hostname."))
        return findings, info
    except (socket.timeout, socket.gaierror, ConnectionError, ssl.SSLError, OSError) as e:
        findings.append(_finding(
            "high", "Could not establish a TLS connection",
            f"Connecting to {host}:{port} over TLS failed: {e}.",
            "If the site is meant to be reachable over HTTPS, users cannot connect securely.",
            "Confirm the host serves HTTPS on this port and the firewall allows it."))
        return findings, info

    # Protocol version age
    proto = info.get("protocol") or ""
    if proto in ("TLSv1", "TLSv1.1", "SSLv3"):
        findings.append(_finding(
            "high", f"Outdated TLS protocol negotiated ({proto})",
            f"The server negotiated {proto}, which is deprecated.",
            "Old TLS versions have known weaknesses and are rejected by modern browsers.",
            "Disable everything below TLS 1.2 and prefer TLS 1.3."))

    # Expiry
    not_after = cert.get("notAfter")
    if not_after:
        try:
            exp = _dt.datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
            days = (exp.replace(tzinfo=_dt.timezone.utc) - _dt.datetime.now(_dt.timezone.utc)).days
            info["cert_expires_in_days"] = days
            info["cert_not_after"] = not_after
            if days < 0:
                findings.append(_finding(
                    "high", "TLS certificate has expired",
                    f"The certificate expired on {not_after} ({-days} days ago).",
                    "Browsers block the site with a security warning until it is renewed.",
                    "Renew the certificate now and set up auto-renewal (e.g. ACME/Let's Encrypt)."))
            elif days < 21:
                findings.append(_finding(
                    "medium", f"TLS certificate expires in {days} days",
                    f"The certificate for {host} expires on {not_after}.",
                    "If it lapses, the whole site goes down with a browser security warning.",
                    "Renew it and automate renewal so this does not recur."))
        except ValueError:
            pass

    issuer = dict(x[0] for x in cert.get("issuer", ())) if cert.get("issuer") else {}
    info["cert_issuer"] = issuer.get("organizationName") or issuer.get("commonName")
    return findings, info


def fetch(url):
    """One GET, following redirects. Returns (response, redirect_chain, findings)."""
    findings = []
    chain = []

    class _Track(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            chain.append((req.full_url, code, newurl))
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(_Track)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        resp = opener.open(req, timeout=TIMEOUT)
        body = resp.read(2048)  # read a little, then stop; we only need headers
        return resp, chain, findings, body
    except urllib.error.HTTPError as e:
        # An HTTP error still carries headers worth inspecting.
        return e, chain, findings, b""
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
        findings.append(_finding(
            "high", "Site could not be reached",
            f"A GET to {url} failed: {e}.",
            "If the site should be live, this is an outage for every user.",
            "Check DNS, the server process and any load balancer or firewall in front of it."))
        return None, chain, findings, b""


def check_headers(headers):
    findings = []
    present = {k.lower(): v for k, v in headers.items()}
    for name, (sev, why, fix) in SECURITY_HEADERS.items():
        if name not in present:
            findings.append(_finding(
                sev, f"Missing response header: {name}",
                f"The server response does not include the {name} header.",
                why, fix))
    # Info disclosure
    for name in DISCLOSURE_HEADERS:
        if name in present and present[name].strip():
            findings.append(_finding(
                "low", f"Stack details exposed via {name} header",
                f"The response advertises '{name}: {present[name]}'.",
                "Naming the exact server or framework version helps an attacker pick known exploits.",
                f"Remove or blank the {name} header at the web server or proxy."))
    return findings


def check_cookies(headers):
    findings = []
    raw_cookies = headers.get_all("Set-Cookie") if hasattr(headers, "get_all") else []
    for raw in raw_cookies or []:
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(raw)
        except http.cookies.CookieError:
            continue
        for name, morsel in jar.items():
            low = raw.lower()
            if "secure" not in low:
                findings.append(_finding(
                    "high", f"Cookie '{name}' is not marked Secure",
                    f"The Set-Cookie for '{name}' has no Secure attribute.",
                    "The cookie can be sent over plain HTTP and captured by a network attacker.",
                    "Add the Secure attribute so the cookie is only sent over HTTPS."))
            if "httponly" not in low:
                findings.append(_finding(
                    "medium", f"Cookie '{name}' is not HttpOnly",
                    f"The Set-Cookie for '{name}' has no HttpOnly attribute.",
                    "Injected JavaScript (XSS) can read the cookie, which may be a session token.",
                    "Add the HttpOnly attribute unless the cookie must be read by scripts."))
            if "samesite" not in low:
                findings.append(_finding(
                    "low", f"Cookie '{name}' has no SameSite attribute",
                    f"The Set-Cookie for '{name}' does not set SameSite.",
                    "The cookie is sent on cross-site requests, which enables CSRF.",
                    "Add 'SameSite=Lax' (or Strict) unless cross-site use is required."))
    return findings


def check_redirect(url, chain):
    findings = []
    if url.startswith("http://"):
        hops = [c for c in chain if c[2].startswith("https://")]
        if not hops:
            findings.append(_finding(
                "high", "HTTP is not redirected to HTTPS",
                f"Requesting {url} did not redirect to an https:// URL.",
                "Users and links that start on HTTP stay unencrypted for the whole session.",
                "Add a permanent redirect from HTTP to HTTPS at the web server or load balancer."))
    return findings


def audit_url(url):
    result = {"url": url, "findings": [], "info": {}, "redirects": []}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
        result["url"] = url

    host = urllib.parse.urlsplit(url).hostname
    if url.startswith("https://") and host:
        tls_f, tls_info = check_tls(host)
        result["findings"].extend(tls_f)
        result["info"].update(tls_info)

    resp, chain, fetch_f, _ = fetch(url)
    result["findings"].extend(fetch_f)
    result["redirects"] = [{"from": a, "status": c, "to": b} for a, c, b in chain]
    if resp is not None:
        headers = resp.headers
        result["info"]["status"] = getattr(resp, "status", getattr(resp, "code", None))
        result["info"]["final_url"] = resp.geturl() if hasattr(resp, "geturl") else url
        result["findings"].extend(check_headers(headers))
        result["findings"].extend(check_cookies(headers))
    result["findings"].extend(check_redirect(url, chain))
    return result


import urllib.parse  # noqa: E402  (placed after functions for readability)

SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


def main():
    ap = argparse.ArgumentParser(description="Passive live-site health & config check (read-only).")
    ap.add_argument("urls", nargs="+", help="One or more URLs you are authorized to test.")
    ap.add_argument("--json-out", help="Write the full result as JSON to this path.")
    args = ap.parse_args()

    results = [audit_url(u) for u in args.urls]
    unreachable = 0

    for r in results:
        r["findings"].sort(key=lambda f: SEV_ORDER.get(f["severity"], 9))
        counts = {s: sum(1 for f in r["findings"] if f["severity"] == s) for s in ("high", "medium", "low")}
        info = r["info"]
        print(f"\n=== {r['url']} ===")
        if info.get("status"):
            line = f"status {info['status']}"
            if info.get("protocol"):
                line += f" · {info['protocol']}"
            if info.get("cert_expires_in_days") is not None:
                line += f" · cert expires in {info['cert_expires_in_days']}d"
            if info.get("cert_issuer"):
                line += f" · issuer {info['cert_issuer']}"
            print(line)
        else:
            unreachable += 1
        for hop in r["redirects"]:
            print(f"  redirect {hop['status']}: {hop['from']} -> {hop['to']}")
        print(f"  findings: {counts['high']} high · {counts['medium']} medium · {counts['low']} low")
        for f in r["findings"]:
            print(f"  [{f['severity'].upper():6}] {f['title']}")
            print(f"           why: {f['why']}")
            print(f"           fix: {f['fix']}")

    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump({"generated": _dt.datetime.now(_dt.timezone.utc).isoformat(), "results": results}, fh, indent=2)
        print(f"\nJSON written to {args.json_out}")

    return 1 if unreachable == len(results) else 0


if __name__ == "__main__":
    sys.exit(main())
