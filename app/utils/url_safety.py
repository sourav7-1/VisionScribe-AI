import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from app.utils.errors import AppError


async def validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AppError("invalid_url", "Enter a valid HTTP or HTTPS video URL.")
    if parsed.username or parsed.password:
        raise AppError("invalid_url", "URLs containing credentials are not supported.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise AppError("unsafe_private_url", "Private or local network URLs are not allowed.")
    try:
        records = await asyncio.get_running_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(hostname, parsed.port, type=socket.SOCK_STREAM)
        )
    except socket.gaierror as exc:
        raise AppError("unreachable_url", "The video URL hostname could not be resolved.") from exc
    addresses = {item[4][0].split("%", 1)[0] for item in records}
    if not addresses:
        raise AppError("unreachable_url", "The video URL hostname could not be resolved.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise AppError("unsafe_private_url", "Private or local network URLs are not allowed.")

