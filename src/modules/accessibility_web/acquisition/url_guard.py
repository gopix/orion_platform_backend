"""
url_guard.py - SSRF-safe URL validation and fetch for the accessibility_web
scan pipeline.

Centralizes everything scan_service.run_scan() needs before making an
outbound HTTP request on behalf of a user-supplied scan URL:

    scan URL
        |
        +-- scheme check (http/https only)
        +-- domain-match check: the URL's host must equal, or be a
        |   subdomain of, the registered website's base_url host - entry
        |   URL only, not redirect targets (a legitimate redirect can
        |   land on a different domain, e.g. a CDN)
        +-- DNS resolution (every resolved address, not just the first)
        +-- private/reserved-IP rejection (stdlib ipaddress), with a
        |   config-level allowlist (settings.scan_private_ip_allowlist)
        |   for deliberately-permitted internal targets
        +-- fetch with redirects disabled; each redirect hop is re-run
        |   through DNS resolution + IP rejection + allowlist before being
        |   followed, up to MAX_REDIRECTS hops
        +-- response body capped at MAX_RESPONSE_BYTES

Known limitation: this validates each hop's resolved IP immediately
before connecting to it, but it does not pin the TCP connection to that
exact address the way requests/urllib3 issues the request - a well-
resourced attacker controlling DNS for the target host with a very short
TTL could still rebind between validation and connection ("DNS
rebinding"). Closing that fully means either a vetted connection-pinning
library or a hand-rolled urllib3 connection-pool override, and both carry
real risk of a subtle TLS-hostname-verification regression if done
carelessly - safer to ship the validate-immediately-before-connect
version (which narrows the window to milliseconds and rules out anything
but a targeted, dedicated rebinding attack against this one endpoint)
than a half-correct pinning hack. This module also does no global
monkeypatching of socket.getaddrinfo for that same reason - it stays
thread-safe under concurrent scans (FastAPI runs sync BackgroundTasks in
a thread pool) since every check here operates on local variables only.
"""

import ipaddress
import socket
from dataclasses import dataclass
from typing import Optional, Union
from urllib.parse import urljoin, urlsplit

import requests

from src.core.config import settings
from src.core.logger import get_logger

logger = get_logger(__name__)

ALLOWED_SCHEMES = {"http", "https"}
MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB - plenty for an HTML page

IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]


class UrlGuardError(ValueError):
    """
    Raised when a URL (the entry scan URL, or a redirect target it leads
    through) fails validation. The message is safe to surface to a caller
    or log verbatim - it never includes anything the caller didn't already
    provide.
    """


@dataclass(frozen=True)
class _AllowlistEntry:
    network: Optional[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]]
    hostname: Optional[str]


def _parse_allowlist(raw: str) -> list[_AllowlistEntry]:
    entries = []
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            network = ipaddress.ip_network(item, strict=False)
            entries.append(_AllowlistEntry(network=network, hostname=None))
        except ValueError:
            entries.append(_AllowlistEntry(network=None, hostname=item.lower()))
    return entries


def _is_allowlisted(ip: IPAddress, hostname: str, allowlist: list[_AllowlistEntry]) -> bool:
    hostname = hostname.lower()
    for entry in allowlist:
        if entry.hostname is not None and entry.hostname == hostname:
            return True
        if entry.network is not None and ip in entry.network:
            return True
    return False


def _is_disallowed_ip(ip: IPAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve(hostname: str) -> list[IPAddress]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise UrlGuardError(f"Could not resolve host '{hostname}': {exc}") from exc

    addresses: list[IPAddress] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if ip not in addresses:
            addresses.append(ip)

    if not addresses:
        raise UrlGuardError(f"Could not resolve host '{hostname}' to any address")
    return addresses


def same_domain_or_subdomain(candidate_host: str, allowed_host: str) -> bool:
    """
    True if candidate_host and allowed_host are the same site: exactly
    equal, or one is a subdomain of the other - in EITHER direction.
    e.g. "www.example.com" and "example.com" are related both ways, so
    a website registered under either host form accepts scan/crawl URLs
    on the other. Originally one-directional (candidate had to be a
    subdomain of allowed); widened after ScanService.crawl_website()'s
    sitemap-based discovery hit real sites that declare their canonical
    host (sitemap.xml, <link rel="canonical">) as the apex while being
    registered here under the "www." form, or vice versa - without the
    reverse direction those sitemap URLs would be accepted by
    ScanService.create_scan()'s domain gate and then rejected right back
    out by THIS function's other call site inside safe_fetch() below,
    contradicting the 202 the caller already got.

    Sibling subdomains are still correctly rejected either way (e.g.
    "blog.example.com" vs "www.example.com" - neither is an ancestor of
    the other), and this never widens to a genuinely different
    registrable domain - only ancestor/descendant relationships within
    the same domain tree.

    This is NOT itself an SSRF check - every actual fetch (the scan URL,
    and each redirect hop it leads through) still goes through
    validate_destination()'s DNS resolution + private/reserved-IP
    rejection regardless of domain match. This only gates "is this a URL
    the registered website is allowed to have scanned against it" - an
    abuse-containment check, not an "is this address safe to connect to"
    one.
    """
    candidate_host = candidate_host.lower().rstrip(".")
    allowed_host = allowed_host.lower().rstrip(".")
    if candidate_host == allowed_host:
        return True
    return (
        candidate_host.endswith("." + allowed_host)
        or allowed_host.endswith("." + candidate_host)
    )


def validate_destination(url: str, *, allowlist: list[_AllowlistEntry]) -> None:
    """
    Validate a single URL (the entry URL or a redirect target): scheme,
    DNS resolution, and every resolved address against the private/
    reserved-range check + allowlist. Raises UrlGuardError on failure.
    Does NOT check domain-match - that's the caller's responsibility, and
    only applies to the entry URL (see safe_fetch).
    """
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise UrlGuardError(f"URL scheme '{parts.scheme}' is not allowed (only http/https)")
    if not parts.hostname:
        raise UrlGuardError("URL has no hostname")

    hostname = parts.hostname
    for ip in _resolve(hostname):
        if _is_disallowed_ip(ip) and not _is_allowlisted(ip, hostname, allowlist):
            raise UrlGuardError(
                f"URL host '{hostname}' resolves to a private/reserved address "
                f"({ip}) that is not on the allowlist"
            )


def safe_fetch(
    url: str,
    *,
    allowed_website_host: str,
    timeout: float,
    user_agent: str,
) -> requests.Response:
    """
    Fetch `url` after validating it and every redirect hop it leads
    through. `allowed_website_host` is the registered website's base_url
    host - the entry URL's host must equal it or be a subdomain of it;
    redirect targets are exempt from that specific check (a legitimate
    redirect can land on a different domain, e.g. a CDN) but still go
    through full scheme + DNS + IP-range + allowlist validation like any
    other destination. Raises UrlGuardError if any check fails.
    """
    allowlist = _parse_allowlist(settings.scan_private_ip_allowlist)

    entry_host = urlsplit(url).hostname
    if not entry_host:
        raise UrlGuardError("URL has no hostname")
    if not same_domain_or_subdomain(entry_host, allowed_website_host):
        raise UrlGuardError(
            f"URL host '{entry_host}' does not match the registered website's "
            f"host '{allowed_website_host}'"
        )

    current_url = url
    with requests.Session() as session:
        for hop in range(MAX_REDIRECTS + 1):
            validate_destination(current_url, allowlist=allowlist)

            response = session.get(
                current_url,
                timeout=timeout,
                headers={"User-Agent": user_agent},
                allow_redirects=False,
                stream=True,
            )

            if response.is_redirect:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise UrlGuardError("Redirect response had no Location header")
                if hop >= MAX_REDIRECTS:
                    raise UrlGuardError(f"Too many redirects (> {MAX_REDIRECTS})")
                current_url = urljoin(current_url, location)
                continue

            return _read_capped(response)

    raise UrlGuardError(f"Too many redirects (> {MAX_REDIRECTS})")


def _read_capped(response: requests.Response) -> requests.Response:
    """
    Drain response.raw up to MAX_RESPONSE_BYTES and attach it as
    response._content, so response.text/.json() work normally afterward
    while the amount actually read off the wire stays bounded.
    """
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            response.close()
            raise UrlGuardError(f"Response exceeded {MAX_RESPONSE_BYTES} bytes")
    response._content = b"".join(chunks)
    return response
