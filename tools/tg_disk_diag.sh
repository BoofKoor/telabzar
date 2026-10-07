#!/usr/bin/env bash
# Why did the local Bot API directory (tg-bot-api-data) fill the disk?
# Read-only: deletes and changes nothing. It writes only its report and one temp
# file, and creates a TEMP table that dies with its own psql session.
# Run on the master:
#   cd /root/telabzar && git fetch -q origin claude/focused-keller-85llm3 &&
#   git show FETCH_HEAD:tools/tg_disk_diag.sh > /root/tlz-diag.sh && bash /root/tlz-diag.sh
# Output: /root/tlz-diag.txt (English on purpose: server terminals do not shape Persian).
DIR=${TLZ_DIR:-/root/telabzar}
cd "$DIR" || { echo "$DIR not found"; exit 1; }
OUT=${OUT:-/root/tlz-diag.txt}
FS=${TMPDIR:-/tmp}/tlz_fs.tsv
PSQL=${PSQL:-"docker compose exec -T postgres psql -U telabzar -d telabzar -X -P pager=off"}
TG=$(docker volume inspect telabzar_tg-bot-api-data -f '{{.Mountpoint}}' 2>/dev/null)
export TZ=UTC   # every time in UTC, to line up with the DB and docker logs

{
echo "### 1. clock / disk"
date; uptime
df -h / "$TG" 2>&1
docker system df 2>&1

echo; echo "### 2. services + start times"
docker compose ps --format 'table {{.Service}}\t{{.Status}}' 2>&1
for s in bot worker download-worker gateway local-bot-api postgres; do
  printf '%-16s %s\n' "$s" "$(docker inspect -f '{{.State.StartedAt}}' "telabzar-$s-1" 2>/dev/null)"
done
docker volume inspect telabzar_tg-bot-api-data -f 'tg volume created: {{.CreatedAt}}' 2>&1
docker volume inspect telabzar_pg-data -f 'pg  volume created: {{.CreatedAt}}' 2>&1

echo; echo "### 3. code + cron"
git log -3 --format='%h %ci %s'
git reflog --date=iso -8
crontab -l 2>&1 | grep -v '^#'

echo; echo "### 4. telegram dir: size per subdir, then files per day"
du -sh "$TG"/*/* 2>/dev/null | sort -h | tail -12 | sed "s#$TG/##"
for d in "$TG"/*/*/; do
  echo "== ${d#$TG/}"
  find "$d" -type f -printf '%TY-%Tm-%Td %s\n' |
    awk '{c[$1]++; s[$1]+=$2} END{for(k in c) printf "   %s %5d files %8.1f GB\n",k,c[k],s[k]/2^30}' | sort | tail -12
done

echo; echo "### 5. videos fetched on 2026-10-04, per hour (UTC)"
find "$TG"/*/videos -type f -newermt 2026-10-04 ! -newermt 2026-10-05 -printf '%TH\n' 2>/dev/null | sort | uniq -c

echo; echo "### 6. database"
$PSQL <<'SQL'
\echo '--- 6a non-default settings (no row = default)'
SELECT key, value, updated_at FROM settings
 WHERE key IN ('max_file_mb','safety_enabled','safety_scan_pixels','safety_video_frames',
               'dl_max_size_mb','downloader_enabled','dl_link_days','stream_base')
 ORDER BY key;
\echo '--- 6b videos per day (last 14 days)'
SELECT date(created_at AT TIME ZONE 'UTC') AS day,
       coalesce(source,'upload') AS src, count(*) AS n,
       pg_size_pretty(sum(size)) AS total,
       count(*) FILTER (WHERE size > 500*1024^2) AS over_500mb
  FROM files WHERE kind = 'video' AND created_at > now() - interval '14 days'
 GROUP BY 1,2 ORDER BY 1,2;
\echo '--- 6c who sent videos, Oct 3-5 (internal ids)'
SELECT owner_id, coalesce(source,'upload') AS src, count(*) AS n, pg_size_pretty(sum(size)) AS total
  FROM files WHERE kind = 'video' AND created_at >= '2026-10-03' AND created_at < '2026-10-06'
 GROUP BY 1,2 ORDER BY sum(size) DESC NULLS LAST LIMIT 10;
\echo '--- 6d video files that had an operation, per day (each one = a full fetch)'
SELECT day, count(*) AS files, pg_size_pretty(sum(size)) AS total
  FROM (SELECT DISTINCT date(j.created_at AT TIME ZONE 'UTC') AS day, j.file_id, f.size
          FROM jobs j JOIN files f ON f.id = j.file_id
         WHERE f.kind = 'video' AND j.created_at > now() - interval '14 days') x
 GROUP BY day ORDER BY day;
\echo '--- 6e ops on video, Oct 3-5'
SELECT j.op, count(*) AS jobs, count(DISTINCT j.file_id) AS files
  FROM jobs j JOIN files f ON f.id = j.file_id
 WHERE f.kind = 'video' AND j.created_at >= '2026-10-03' AND j.created_at < '2026-10-06'
 GROUP BY 1 ORDER BY 2 DESC;
\echo '--- 6f video links (last request day; the deploy day also includes old links stamped by the migration)'
SELECT date(dl_token_at AT TIME ZONE 'UTC') AS day, count(*) AS n, pg_size_pretty(sum(size)) AS total
  FROM files WHERE dl_token IS NOT NULL AND kind = 'video'
 GROUP BY 1 ORDER BY 1 DESC LIMIT 10;
SQL

echo; echo "### 7. each cached video matched to its DB row by exact byte size"
find "$TG"/*/videos -type f -printf '%s\t%T@\n' 2>/dev/null > "$FS"
echo "files on disk: $(wc -l < "$FS")"
if [ -s "$FS" ]; then
{ echo "CREATE TEMP TABLE fs(size bigint, mtime double precision);"
  echo "COPY fs FROM STDIN;"; cat "$FS"; echo '\.'
  cat <<'SQL'
CREATE TEMP TABLE m AS
SELECT fs.size, to_timestamp(fs.mtime) AS fetched, x.*
  FROM fs LEFT JOIN LATERAL (
       SELECT count(*) AS rows,
              string_agg(DISTINCT coalesce(f.source,'upload'), ',') AS src,
              bool_or(f.dl_token IS NOT NULL) AS link,
              bool_or(EXISTS (SELECT 1 FROM jobs j WHERE j.file_id = f.id)) AS op,
              min(f.created_at) AS created
         FROM files f WHERE f.size = fs.size) x ON true;
\echo '--- 7a summary'
SELECT coalesce(src,'NO MATCH') AS src, link, op,
       CASE WHEN created IS NULL THEN '-'
            WHEN fetched - created < interval '15 min' THEN 'fetched <15min after arrival'
            ELSE 'fetched later' END AS when_fetched,
       count(*) AS files, pg_size_pretty(sum(size)) AS total
  FROM m GROUP BY 1,2,3,4 ORDER BY sum(size) DESC;
\echo '--- 7b detail (Oct 4)'
SELECT to_char(fetched AT TIME ZONE 'UTC','MM-DD HH24:MI') AS fetched,
       round(size/1024.0^2) AS mb, coalesce(src,'NO MATCH') AS src, rows, link, op,
       round(extract(epoch FROM fetched - created)/60) AS min_after_arrival
  FROM m WHERE fetched >= '2026-10-04' AND fetched < '2026-10-05' ORDER BY fetched;
SQL
} | $PSQL
fi

echo; echo "### 8. logs (only since each container started)"
echo "--- 8a jobs per day (UTC)"
for s in worker download-worker; do
  docker compose logs -t --no-log-prefix --since 240h "$s" 2>/dev/null |
    grep -E '→ [^ ]+:(run_screen|run_op|run_download)\(' |
    sed -E 's/^([0-9-]{10})T.*:(run_screen|run_op|run_download)\(.*/\1 \2/' | sort | uniq -c
done
echo "--- 8b run_screen per hour on 2026-10-04"
docker compose logs -t --no-log-prefix --since 240h worker 2>/dev/null |
  grep -E '^2026-10-04T.*→ [^ ]+:run_screen\(' | cut -c12-13 | sort | uniq -c
echo "--- 8c gateway /s /dl requests per day, and distinct links"
docker compose logs -t --no-log-prefix --since 240h gateway 2>/dev/null |
  grep -E '"(GET|HEAD) /(s|dl)/' | cut -c1-10 | sort | uniq -c
docker compose logs --no-log-prefix --since 240h gateway 2>/dev/null |
  grep -oE '"(GET|HEAD) /(s|dl)/[A-Za-z0-9_-]+' | awk '{print $2}' | sort -u | wc -l
} > "$OUT" 2>&1

echo "done: $OUT ($(wc -l < "$OUT") lines)"
