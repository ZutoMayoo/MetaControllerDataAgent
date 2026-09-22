WITH et AS (
  SELECT "beforeEventBuffer", "afterEventBuffer" FROM "EventType" WHERE id = 901002
),
existing AS (
  SELECT b."startTime", b."endTime",
         (SELECT e."beforeEventBuffer" FROM "EventType" e WHERE e.id = b."eventTypeId") AS ex_before,
         (SELECT e."afterEventBuffer" FROM "EventType" e WHERE e.id = b."eventTypeId") AS ex_after
  FROM "Booking" b
  JOIN "EventType" e ON e.id = b."eventTypeId"
  WHERE e.slug = 'bench-buffer-existing'
    AND b."startTime"::date = DATE '2026-11-03'
    AND b."status" = 'accepted'
),
windows AS (
  SELECT 'BENCH-BUF-OK' AS label, TIMESTAMP '2026-11-03 09:00:00' AS ws, TIMESTAMP '2026-11-03 09:30:00' AS we
  UNION ALL
  SELECT 'BENCH-BUF-EARLY', TIMESTAMP '2026-11-03 09:30:00', TIMESTAMP '2026-11-03 10:00:00'
  UNION ALL
  SELECT 'BENCH-BUF-LATE', TIMESTAMP '2026-11-03 11:40:00', TIMESTAMP '2026-11-03 12:10:00'
)
SELECT w.label
FROM windows w
CROSS JOIN et
WHERE NOT EXISTS (
  SELECT 1 FROM existing x
  WHERE w.ws < x."endTime" AND w.we > x."startTime"
     OR (w.ws - (et."beforeEventBuffer" || ' minutes')::interval) < x."endTime" AND w.ws > x."startTime"
     OR w.we < x."endTime" + (et."afterEventBuffer" || ' minutes')::interval AND w.we > x."startTime"
)
ORDER BY w.label