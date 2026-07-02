-- Monthly ride counts per station. The demo's canonical rollup query.
-- Run: python3 db/query.py "$(cat sql/monthly_rides.sql)"
SELECT s.name, r.month, count(*) AS rides
FROM rides r
JOIN stations s USING (station_id)
GROUP BY s.name, r.month
ORDER BY r.month, rides DESC;
