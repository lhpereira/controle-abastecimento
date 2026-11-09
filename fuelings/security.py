"""Utilitários de segurança: CSP, IP real do cliente e exportação CSV segura."""

import ipaddress

from django.conf import settings


CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)


class ContentSecurityPolicyMiddleware:
    """Só permite scripts e estilos servidos pela própria aplicação (sem inline, sem CDN)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response


# Origens possíveis do cloudflared: o próprio host (loopback) ou redes Docker/LAN.
INTERNAL_NETWORKS = [
    ipaddress.ip_network(network)
    for network in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7")
]


def _is_internal(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in INTERNAL_NETWORKS)


def client_ip(request) -> str | None:
    """IP do cliente para o django-axes.

    Atrás do Cloudflare Tunnel todas as conexões chegam do cloudflared (loopback ou rede
    Docker). Nesse caso o IP real está em CF-Connecting-IP. O cabeçalho só é aceito
    quando a conexão vem de um endereço interno, para não ser forjado por acesso direto.
    """
    remote = request.META.get("REMOTE_ADDR", "")
    if settings.APP_BEHIND_CLOUDFLARE and _is_internal(remote):
        forwarded = request.META.get("HTTP_CF_CONNECTING_IP", "").strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return remote or None


FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def csv_safe(value):
    """Neutraliza fórmulas em células de texto (CSV injection).

    Excel e LibreOffice executam células iniciadas por = + - @. Um apóstrofo à frente
    faz a planilha tratar o conteúdo como texto. Números não são alterados.
    """
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value
