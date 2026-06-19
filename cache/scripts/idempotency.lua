--[[
    Idempotency Key Manager
    =======================
    Atomic check-and-set for idempotency keys.

    Prevents duplicate processing of retried HTTP requests.
    The client sends a UUID in X-Idempotency-Key.
    This script atomically checks if the key exists and either:
        a) Returns the cached response (duplicate request — replay).
        b) Reserves the key and signals the caller to process the request.

    Two-phase protocol:
        Phase 1 — RESERVE: called before processing the request.
                   Sets the key to "processing" with a short TTL.
                   Returns "new" (proceed) or "processing" (wait/retry)
                   or the cached response JSON (replay).

        Phase 2 — STORE: called after the request completes successfully.
                   Replaces "processing" with the serialised response.
                   Sets the long TTL (86400 seconds = 24 hours).

    KEYS[1]  : idempotency_key  — e.g. "idem:550e8400-..."

    ARGV[1]  : phase            — "reserve" or "store"
    ARGV[2]  : response_json    — (store phase only) serialised HTTP response
    ARGV[3]  : processing_ttl   — (reserve phase only) seconds to hold
                                    "processing" state (default 30)
    ARGV[4]  : store_ttl        — (store phase only) seconds to keep
                                    cached response (default 86400)

    Return values:
        reserve phase:
            "new"         — key did not exist, now reserved as "processing"
            "processing"  — another request is currently processing this key
            <json_string> — key exists with a cached response, replay it

        store phase:
            "ok"          — response stored successfully
            "conflict"    — key is in unexpected state (should not happen)
]]

local idem_key       = KEYS[1]
local phase          = ARGV[1]

if phase == 'reserve' then
    local processing_ttl = tonumber(ARGV[3]) or 30

    -- Atomically get the current value.
    local existing = redis.call('GET', idem_key)

    if existing == false then
        -- Key does not exist — this is a new request.
        -- Reserve the key immediately with a short TTL.
        -- SET NX ensures atomicity: if two requests race, only one wins.
        local set_result = redis.call(
            'SET', idem_key, 'processing',
            'EX', processing_ttl,
            'NX'
        )
        if set_result then
            return 'new'
        else
            -- Lost the race — another request reserved it in the same moment.
            return 'processing'
        end

    elseif existing == 'processing' then
        -- Another request is currently processing this key.
        -- Tell the caller to wait and retry.
        return 'processing'

    else
        -- Key holds a cached response from a previous successful request.
        -- Return it directly — the caller will replay the response.
        return existing
    end

elseif phase == 'store' then
    local response_json = ARGV[2]
    local store_ttl     = tonumber(ARGV[4]) or 86400

    -- Only store if the key is currently in "processing" state.
    -- This prevents overwriting a valid cached response if somehow
    -- store is called twice (should not happen in normal flow).
    local existing = redis.call('GET', idem_key)

    if existing == 'processing' or existing == false then
        redis.call('SET', idem_key, response_json, 'EX', store_ttl)
        return 'ok'
    else
        -- Key already has a stored response — do not overwrite.
        return 'conflict'
    end

else
    -- Unknown phase — return error signal.
    return redis.error_reply('ERR unknown idempotency phase: ' .. tostring(phase))
end