"""Common DNS provider abstractions and utilities."""

from tools.common.dns.provider import DNSProvider
from tools.common.dns.client import DNSClient
from tools.common.dns.desec_provider import DesecProvider

__all__ = ["DNSProvider", "DNSClient", "DesecProvider"]
