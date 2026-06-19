--[[
    Token Bucket Rate Limiter
    =========================
    A generic, atomic token bucket implementation for Redis.

    This script is loaded into Redis once at application startup via
    SCRIPT LOAD and called via EVALSHA on every rate-limited request.

    KEYS[1]  : bucket_key   — The Redis key storing this bucket's state.
                               Format matches the naming convention in cache/keys.py.
                               e.g. "rl:login:192.168.1.1"

    ARGV[1]  : capacity     — Maximum number of tokens the bucket can hold.
                               Also the initial token count for a new bucket.
                               Type: float (as string), e.g. "10"

    ARGV[2]  : rate         — Tokens added per second (refill rate).
                               Type: float (as string), e.g. "2.0"
                               A rate of 2.0 means one token every 500ms.

    ARGV[3]  : requested    — Number of tokens this request wants to consume.
                               Usually "1" for standard endpoints.
                               Use higher values for weight-based limiting
                               (e.g. bulk operations that cost more).
                               Type: float (as string), e.g. "1"

    ARGV[4]  : ttl_seconds  — TTL to set on the bucket key in seconds.
                               Prevents orphaned keys for inactive users.
                               Should be >= capacity / rate.
                               e.g. capacity=10, rate=2 → ttl >= 5
                               Recommended: set to 2 × (capacity / rate)
                               Type: integer (as string), e.g. "60"

    Return value — a Redis array (table in Lua) with 3 elements:
        [1]  allowed        integer — 1 if the request is allowed, 0 if denied
        [2]  remaining      integer — tokens remaining AFTER this request
                                       (0 if denied, actual remaining if allowed)
        [3]  retry_after    integer — seconds until enough tokens refill to
                                       allow one request (0 if allowed)

    Algorithm:
        1. Read current bucket state from Redis (tokens, last_refill_time).
        2. Get current server time from Redis (avoids clock skew between servers).
        3. Compute elapsed seconds since last refill.
        4. Add (elapsed × rate) tokens, capped at capacity.
        5. If tokens >= requested: subtract requested, allow request.
        6. If tokens < requested: deny, compute retry_after.
        7. Write new state back with TTL.
        8. Return [allowed, remaining, retry_after].
]]

-- ── Parse arguments ───────────────────────────────────────────────────────────
local bucket_key   = KEYS[1]
local capacity     = tonumber(ARGV[1])
local rate         = tonumber(ARGV[2])
local requested    = tonumber(ARGV[3])
local ttl_seconds  = tonumber(ARGV[4])

-- ── Get current server time from Redis ───────────────────────────────────────
-- redis.call('TIME') returns {unix_seconds, microseconds}.
-- We convert to a float with microsecond precision for accurate refill
-- calculations at high request rates.
local time_result  = redis.call('TIME')
local now          = tonumber(time_result[1]) + tonumber(time_result[2]) / 1e6

-- ── Read current bucket state ─────────────────────────────────────────────────
-- The bucket is stored as a Redis Hash with two fields:
--   tokens       : current token count (float stored as string)
--   last_refill  : unix timestamp of last refill (float stored as string)
--
-- Using HMGET to fetch both fields in a single round-trip.
local bucket       = redis.call('HMGET', bucket_key, 'tokens', 'last_refill')
local current_tokens   = tonumber(bucket[1])
local last_refill_time = tonumber(bucket[2])

-- ── Handle new bucket (key does not exist yet) ────────────────────────────────
-- If either field is nil, this is a new or expired bucket.
-- Initialise with full capacity and current time.
if current_tokens == nil or last_refill_time == nil then
    current_tokens   = capacity
    last_refill_time = now
end

-- ── Refill tokens based on elapsed time ──────────────────────────────────────
-- How many seconds have passed since the last request touched this bucket?
local elapsed = now - last_refill_time

-- Tokens accumulated during the elapsed period.
-- Capped at capacity — the bucket cannot overflow.
local refill_amount = elapsed * rate
current_tokens = math.min(capacity, current_tokens + refill_amount)

-- ── Decide: allow or deny ─────────────────────────────────────────────────────
local allowed      = 0
local remaining    = 0
local retry_after  = 0

if current_tokens >= requested then
    -- ── Allow ────────────────────────────────────────────────────────────────
    allowed         = 1
    current_tokens  = current_tokens - requested

    -- Remaining is floored to an integer for the API response header.
    -- The internal state retains full float precision.
    remaining       = math.floor(current_tokens)
    retry_after     = 0

    -- Write updated state back to Redis.
    -- last_refill is updated to now so the next request calculates
    -- elapsed from this moment, not from the previous request.
    redis.call('HMSET', bucket_key,
        'tokens',      tostring(current_tokens),
        'last_refill', tostring(now)
    )
    redis.call('EXPIRE', bucket_key, ttl_seconds)

else
    -- ── Deny ─────────────────────────────────────────────────────────────────
    allowed    = 0
    remaining  = 0

    -- How many more tokens are needed?
    local tokens_needed = requested - current_tokens

    -- How many seconds until that many tokens refill?
    -- retry_after is rounded up to the nearest whole second so the
    -- client knows the minimum wait time before retrying.
    retry_after = math.ceil(tokens_needed / rate)

    -- Still update last_refill and the current token count in Redis.
    -- This prevents "phantom refill" — if we don't write the refilled
    -- tokens back, the next denied request recalculates from scratch and
    -- could give a misleadingly long retry_after.
    redis.call('HMSET', bucket_key,
        'tokens',      tostring(current_tokens),
        'last_refill', tostring(now)
    )
    redis.call('EXPIRE', bucket_key, ttl_seconds)
end

-- ── Return result ─────────────────────────────────────────────────────────────
-- Redis Lua arrays are 1-indexed. The Python caller receives this as a list.
return {allowed, remaining, retry_after}