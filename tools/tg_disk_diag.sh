#!/usr/bin/env bash
# Why did the local Bot API directory (tg-bot-api-data) fill the disk?
# Read-only: deletes and changes nothing. It writes only its report (and, with
# --save-list, one listing file), and creates TEMP tables that die with their
# own psql session. The bot token (it is the directory name) is masked in the report.
#
# Run on the master:
#   cd /root/telabzar && git fetch -q origin claude/focused-keller-85llm3 &&
#   git show FETCH_HEAD:tools/tg_disk_diag.sh > /root/tlz-diag.sh && bash /root/tlz-diag.sh
#
# Keep the evidence before freeing space: the listing (size, time, type of every
# cached file) is all section 4, 5 and 7 need, so save it first, then point FS_LIST at it:
#   bash /root/tlz-diag.sh --save-list /root/tlz_fs_saved.tsv
#   ... free space, restart postgres ...
#   FS_LIST=/root/tlz_fs_saved.tsv bash /root/tlz-diag.sh
# Output: /root/tlz-diag.txt (English on purpose: server terminals do not shape Persian).
DIR=${TLZ_DIR:-/root/telabzar}
cd "$DIR" || { echo "$DIR not found"; exit 1; }
OUT=${OUT:-/root/tlz-diag.txt}
FS=${TMPDIR:-/tmp}/tlz_fs.tsv
PSQL=${PSQL:-"docker compose exec -T postgres psql -U telabzar -d telabzar -X -P pager=off"}
TG=$(docker volume inspect telabzar_tg-bot-api-data -f '{{.Mountpoint}}' 2>/dev/null)
DAYS=${DAYS:-"2026-10-04 2026-10-05"}
export TZ=UTC   # every time in UTC, to line up with the DB and docker logs

# UTC calendar day of an epoch, in plain arithmetic: mawk (Ubuntu's default awk)
# is not guaranteed to have strftime, and a saved list carries only the epoch.
CIVIL='function day(t,  z, era, doe, yoe, y, doy, mp, d, m) {
  z = int(t / 86400) + 719468; era = int(z / 146097); doe = z - era * 146097
  yoe = int((doe - int(doe / 1460) + int(doe / 36524) - int(doe / 146096)) / 365)
  y = yoe + era * 400; doy = doe - (365 * yoe + int(yoe / 4) - int(yoe / 100))
  mp = int((5 * doy + 2) / 153); d = doy - int((153 * mp + 2) / 5) + 1
  m = mp < 10 ? mp + 3 : mp - 9; if (m <= 2) y++
  return sprintf("%04d-%02d-%02d", y, m, d) }
'

# A bot token is "<digits>:<35 chars>"; the server names its directory after it.
mask() { sed -E 's#[0-9]{5,}:[A-Za-z0-9_-]{20,}#<bot>#g'; }

# One line per cached file: size <TAB> mtime <TAB> type (videos, documents, ...).
list_live() {
  for d in "$TG"/*/*/; do
    t=$(basename "$d")
    find "$d" -type f -printf "%s\t%T@\t$t\n" 2>/dev/null
  done
}

if [ "$1" = "--save-list" ]; then
  dest=${2:?usage: --save-list <file>}
  list_live > "$dest"
  echo "saved $(wc -l < "$dest") files to $dest"
  exit 0
fi

# A saved list from the first version had only two columns (videos): tag them.
if [ -n "$FS_LIST" ]; then
  awk -F'\t' 'NF==2{print $0"\tvideos"; next} NF>=3{print}' "$FS_LIST" > "$FS"
  SRC="saved list $FS_LIST"
else
  list_live > "$FS"
  SRC="live directory"
fi

{
echo "### 1. clock / disk"
date; uptime
df -h / "$TG" 2>&1
docker system df 2>&1
echo "--- container writable layers (a growing local-bot-api here = its temp dir)"
docker ps -a -s --format 'table {{.Names}}\t{{.Status}}\t{{.Size}}' 2>&1

echo; echo "### 2. services + start times"
docker compose ps -a --format 'table {{.Service}}\t{{.Status}}' 2>&1
echo "--- services defined in compose"
docker compose config --services 2>&1 | tr '\n' ' '; echo
for s in bot worker download-worker gateway local-bot-api postgres; do
  printf '%-16s %s\n' "$s" "$(docker inspect -f '{{.State.StartedAt}}' "telabzar-$s-1" 2>/dev/null || echo 'NO CONTAINER')"
done
echo "--- gateway: last log lines"
docker compose logs --tail 15 --no-log-prefix gateway 2>&1 | grep -a . | tail -15
docker volume inspect telabzar_tg-bot-api-data -f 'tg volume created: {{.CreatedAt}}' 2>&1
docker volume inspect telabzar_pg-data -f 'pg  volume created: {{.CreatedAt}}' 2>&1

echo; echo "### 3. code + cron"
git log -3 --format='%h %ci %s'
git reflog --date=iso -8
crontab -l 2>&1 | grep -v '^#'

echo; echo "### 4. telegram dir now (du), then files per day per type from the $SRC"
du -sh "$TG"/*/* 2>/dev/null | sort -h | tail -12 | sed "s#$TG/##"
echo "files listed: $(wc -l < "$FS")"
awk -F'\t' "$CIVIL"'{k=$3" "day($2); c[k]++; s[k]+=$1}
     END{for(k in c) printf "   %-10s %s %5d files %8.1f GB\n", substr(k,1,index(k," ")-1), substr(k,index(k," ")+1), c[k], s[k]/2^30}' "$FS" |
  sort | tail -40

echo; echo "### 5. files fetched per hour (UTC) on: $DAYS"
for day in $DAYS; do
  echo "--- $day   (count  type  hour  GB)"
  awk -F'\t' -v want="$day" "$CIVIL"'{if (day($2) != want) next
       k=$3" "sprintf("%02d", int(($2 % 86400) / 3600)); c[k]++; s[k]+=$1}
       END{for(k in c) printf "%5d  %s  %5.1f\n", c[k], k, s[k]/2^30}' "$FS" | sort -k2,2 -k3,3
done

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
\echo '--- 6c who sent big files, Oct 3-6 (internal ids)'
SELECT owner_id, kind, coalesce(source,'upload') AS src, count(*) AS n, pg_size_pretty(sum(size)) AS total
  FROM files WHERE kind IN ('video','document','archive') AND size > 100*1024^2
   AND created_at >= '2026-10-03' AND created_at < '2026-10-07'
 GROUP BY 1,2,3 ORDER BY sum(size) DESC NULLS LAST LIMIT 12;
\echo '--- 6d files over 100 MB arriving per hour, Oct 4-5'
SELECT to_char(created_at AT TIME ZONE 'UTC','MM-DD HH24') AS hour, kind,
       coalesce(source,'upload') AS src, count(*) AS n, pg_size_pretty(sum(size)) AS total,
       count(DISTINCT owner_id) AS owners
  FROM files WHERE size > 100*1024^2
   AND created_at >= '2026-10-04' AND created_at < '2026-10-06'
 GROUP BY 1,2,3 ORDER BY 1,2,3;
\echo '--- 6e video files that had an operation, per day (each one = a full fetch)'
SELECT day, count(*) AS files, pg_size_pretty(sum(size)) AS total
  FROM (SELECT DISTINCT date(j.created_at AT TIME ZONE 'UTC') AS day, j.file_id, f.size
          FROM jobs j JOIN files f ON f.id = j.file_id
         WHERE f.kind = 'video' AND j.created_at > now() - interval '14 days') x
 GROUP BY day ORDER BY day;
\echo '--- 6f ops on files over 100 MB, Oct 3-6'
SELECT j.op, j.status, count(*) AS jobs, count(DISTINCT j.file_id) AS files
  FROM jobs j JOIN files f ON f.id = j.file_id
 WHERE f.size > 100*1024^2 AND j.created_at >= '2026-10-03' AND j.created_at < '2026-10-07'
 GROUP BY 1,2 ORDER BY 3 DESC;
\echo '--- 6g video links (last request day; the deploy day also includes old links stamped by the migration)'
SELECT date(dl_token_at AT TIME ZONE 'UTC') AS day, count(*) AS n, pg_size_pretty(sum(size)) AS total
  FROM files WHERE dl_token IS NOT NULL AND kind = 'video'
 GROUP BY 1 ORDER BY 1 DESC LIMIT 10;
SQL

echo; echo "### 7. each cached file matched to its DB row by exact byte size ($SRC)"
if [ -s "$FS" ]; then
{ echo "CREATE TEMP TABLE fs(size bigint, mtime double precision, typ text);"
  echo "COPY fs FROM STDIN;"; awk -F'\t' '$1 > 50*1024*1024' "$FS"; echo '\.'
  cat <<'SQL'
CREATE TEMP TABLE m AS
SELECT fs.typ, fs.size, to_timestamp(fs.mtime) AS fetched, x.*
  FROM fs LEFT JOIN LATERAL (
       SELECT count(*) AS rows,
              string_agg(DISTINCT coalesce(f.source,'upload'), ',') AS src,
              bool_or(f.dl_token IS NOT NULL) AS link,
              bool_or(EXISTS (SELECT 1 FROM jobs j WHERE j.file_id = f.id)) AS op,
              min(f.owner_id) AS owner,
              min(f.created_at) AS created
         FROM files f WHERE f.size = fs.size) x ON true;
\echo '--- 7a summary (cached files over 50 MB)'
SELECT typ, coalesce(src,'NO MATCH') AS src, link, op,
       CASE WHEN created IS NULL THEN '-'
            WHEN fetched - created < interval '15 min' THEN 'fetched <15min after arrival'
            ELSE 'fetched later' END AS when_fetched,
       count(*) AS files, pg_size_pretty(sum(size)) AS total
  FROM m GROUP BY 1,2,3,4,5 ORDER BY sum(size) DESC;
\echo '--- 7b which owners those cached files belong to'
SELECT owner, count(*) AS files, pg_size_pretty(sum(size)) AS total
  FROM m GROUP BY 1 ORDER BY sum(size) DESC NULLS LAST LIMIT 10;
\echo '--- 7c detail (Oct 4 20:00 - Oct 6)'
SELECT to_char(fetched AT TIME ZONE 'UTC','MM-DD HH24:MI') AS fetched, typ,
       round(size/1024.0^2) AS mb, coalesce(src,'NO MATCH') AS src, rows, link, op, owner,
       round(extract(epoch FROM fetched - created)/60) AS min_after_arrival
  FROM m WHERE fetched >= '2026-10-04 20:00' AND fetched < '2026-10-06' ORDER BY fetched;
SQL
} | $PSQL
else
  echo "no files listed"
fi

# docker logs carry the odd NUL byte; without -a grep prints "binary file matches"
# and drops every later line.
echo; echo "### 8. logs (only since each container was created)"
docker compose logs -t --no-log-prefix --since 240h worker download-worker 2>/dev/null |
  grep -aE '→ [^ ]+:(run_screen|run_op|run_download)\(' > "${FS}.jobs"
echo "--- 8a jobs started per day (UTC)"
sed -E 's/^([0-9-]{10})T.*:(run_screen|run_op|run_download)\(.*/\1 \2/' "${FS}.jobs" | sort | uniq -c
for day in $DAYS; do
  echo "--- 8b jobs started per hour on $day   (count job hour)"
  grep -a "^${day}T" "${FS}.jobs" |
    sed -E 's/^.{11}(..).*:(run_screen|run_op|run_download)\(.*/\2 \1/' | sort | uniq -c
done
echo "--- 8c run_screen per chat on $DAYS (chat id shortened to its last 4 digits)"
for day in $DAYS; do
  grep -a "^${day}T" "${FS}.jobs" | grep -a ':run_screen(' |
    grep -aoE "'chat_id': [0-9]+" | sed -E "s/.*([0-9]{4})$/$day chat ..\1/" | sort | uniq -c | sort -rn | head -5
done
echo "--- 8d run_op per chat on $DAYS (second argument; last 4 digits)"
for day in $DAYS; do
  grep -a "^${day}T" "${FS}.jobs" | grep -a ':run_op(' |
    sed -nE "s/.*:run_op\([0-9]+, -?[0-9]*([0-9]{4}),.*/$day chat ..\1/p" | sort | uniq -c | sort -rn | head -5
done
echo "--- 8e bot: updates handled per hour on $DAYS"
docker compose logs -t --no-log-prefix --since 240h bot 2>/dev/null | grep -a 'is handled' |
  cut -c1-13 | sort | uniq -c | grep -aE "$(echo "$DAYS" | tr ' ' '|')"
echo "--- 8f gateway /s /dl requests per day, and distinct links"
docker compose logs -t --no-log-prefix --since 240h gateway 2>/dev/null |
  grep -aE '"(GET|HEAD) /(s|dl)/' | cut -c1-10 | sort | uniq -c
docker compose logs --no-log-prefix --since 240h gateway 2>/dev/null |
  grep -aoE '"(GET|HEAD) /(s|dl)/[A-Za-z0-9_-]+' | awk '{print $2}' | sort -u | wc -l
} 2>&1 | mask > "$OUT"

echo "done: $OUT ($(wc -l < "$OUT") lines)"
