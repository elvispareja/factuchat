"""Rate limiting de login (fase 1.3): 5 intentos / 15 min por IP y por cuenta.

Basado en Redis (ventana fija con expiración). El bloqueo progresivo de la CUENTA
vive en la base de datos (users.locked_until) y lo gestionan las funciones auth_*;
esto cubre la barrera por volumen antes de tocar la BD.
"""

import redis

from app.core.config import get_settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after


def check_login_rate(ip: str, account: str) -> None:
    """Lanza RateLimitExceeded si la IP o la cuenta superaron el límite en la ventana."""
    s = get_settings()
    r = get_redis()
    for kind, ident in (("ip", ip), ("acct", account.lower())):
        key = f"rl:login:{kind}:{ident}"
        count = r.incr(key)
        if count == 1:
            r.expire(key, s.login_window_seconds)
        if int(count) > s.login_max_attempts:
            ttl = r.ttl(key)
            raise RateLimitExceeded(retry_after=max(int(ttl), 1))


def reset_account_rate(account: str) -> None:
    """Al iniciar sesión con éxito se limpia el contador de la cuenta (no el de la IP)."""
    get_redis().delete(f"rl:login:acct:{account.lower()}")
