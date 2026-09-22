WITH et AS (
  SELECT "id", "length", "beforeEventBuffer", "afterEventBuffer", "timeZone"
  FROM "EventType"
  WHERE "id" = 901002
),
ex AS (
  SELECT "startTime", "endTime"
  FROM "Booking"
  WHERE "uid" = 'BENCH-BUF-EXISTING'
     OR "title" = 'BENCH-BUF-EXISTING'
  LIMIT 1
),
cand AS (
  SELECT 'W1_after' AS win, ex."endTime" AS s FROM et, ex
  UNION ALL
  SELECT 'W2_before' AS win, ex."endTime" - (et."length" || ' minutes')::interval AS s FROM et, ex  -- hmm
  ...
)