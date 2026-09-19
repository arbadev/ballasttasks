from redis.asyncio import Redis

from app.application.clock import Clock
from app.application.ports.rate_limiter import RateLimitDecision, RateLimitPolicy
from app.infrastructure.rate_limit.window import decision

# KEYS[1] the counter; ARGV: limit, window in ms, now in ms ('' = ask Redis).
# Returns {allowed (0|1), hits counted in this window, ms until the window ends}.
_HIT = """
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
if now_ms == nil then
  local time = redis.call('TIME')
  now_ms = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)
end

local state = redis.call('HMGET', KEYS[1], 'ends_ms', 'count')
local ends_ms = tonumber(state[1])
local count = tonumber(state[2])
if ends_ms == nil or now_ms >= ends_ms then
  ends_ms = now_ms + window_ms
  count = 0
end

local allowed = 0
if count < limit then
  allowed = 1
  count = count + 1
  redis.call('HSET', KEYS[1], 'ends_ms', string.format('%.0f', ends_ms), 'count', count)
  redis.call('PEXPIRE', KEYS[1], ends_ms - now_ms)
end
return {allowed, count, ends_ms - now_ms}
"""


class RedisRateLimiter:
    """Fixed-window counter in Redis, shared by every API process.

    Algorithm: a fixed window that opens at a key's FIRST hit (not on the wall-clock minute,
    so clients do not all reset, and stampede, at the same instant). One small hash per key
    holds the hit count and the window's end.

    Why fixed and not sliding: it is O(1) in memory and commands whatever the limit, and its
    answer maps exactly onto the response headers: "remaining" is a plain subtraction and
    "reset" is the real moment the whole budget returns. A sliding log costs one sorted-set
    entry per hit and has no single reset moment. The price, accepted in ADR 0004: a client
    can spend one budget at the end of a window and the next at the start of the following
    one, so up to 2x ``limit`` in a short burst. Over any longer span the rate still holds.

    Atomicity: read, decide, count and expire are ONE Lua script. Redis runs a script to
    completion before any other command, so concurrent hits from any number of processes
    can never both take the last slot (an INCR followed by a separate EXPIRE could also
    leave a counter with no expiry if the process died in between).

    Expiry: every write sets the key to expire at the window's end, so abandoned keys clean
    themselves up. A blocked hit writes nothing: hammering a closed window neither costs a
    write nor pushes the reset back.

    Time: by default the script reads Redis's own clock (``TIME``), the one clock all API
    processes share, so clock skew between them cannot stretch or shrink a window. ``clock``
    is for tests, which move time instead of sleeping.
    """

    def __init__(self, client: Redis, *, prefix: str = "ratelimit", clock: Clock | None = None):
        self._script = client.register_script(_HIT)
        self._prefix = prefix
        self._clock = clock

    async def hit(self, key: str, policy: RateLimitPolicy) -> RateLimitDecision:
        now_ms = "" if self._clock is None else str(int(self._clock().timestamp() * 1000))
        allowed, count, reset_after_ms = await self._script(
            keys=[f"{self._prefix}:{policy.name}:{key}"],
            args=[policy.limit, policy.window_seconds * 1000, now_ms],
        )
        return decision(
            policy, allowed=bool(allowed), count=int(count), reset_after_ms=int(reset_after_ms)
        )
