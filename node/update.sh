#!/usr/bin/env bash
# به‌روزرسانیِ **درجای** نودِ Telabzar (بدونِ re-join). کدِ تازه را می‌کشد، ایمیجِ نقش را
# دوباره می‌سازد، و کانتینر را با همان env/command بازمی‌سازد.
#
# چرا لازم است: `telabzar update` روی مستر فقط کانتینرهای مستر را نو می‌کند؛ نود ایمیجِ
# جدای خودش را دارد. هر رفعی که کدِ روی نود را عوض کند (مثلِ run_download/_pick_cookies یا
# run_op) با این اسکریپت به نود می‌رسد.
#
# اجرا روی سرورِ نود (با root):
#   cd /opt/telabzar-node/repo && sudo git pull && sudo bash node/update.sh
set -euo pipefail

WORKDIR="/opt/telabzar-node"
REPO="$WORKDIR/repo"
NAME="telabzar-node"

say(){ printf '\033[1;36m==> %s\033[0m\n' "$*"; }
die(){ printf '\033[1;31mخطا: %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "با root اجرا کن (sudo)."
command -v jq >/dev/null || { apt-get update -qq && apt-get install -y -qq jq >/dev/null; }
[[ -d "$REPO/.git" ]] || die "ریپوی نود پیدا نشد ($REPO). اول از پنل نصب کن."
docker inspect "$NAME" >/dev/null 2>&1 || die "کانتینرِ «$NAME» پیدا نشد."

say "خواندنِ env/image/command از کانتینرِ فعلی…"
IMAGE=$(docker inspect "$NAME" --format '{{.Config.Image}}')     # telabzar-node:<role>
ROLE="${IMAGE##*:}"
mapfile -t ENVS < <(docker inspect "$NAME" --format '{{range .Config.Env}}{{println .}}{{end}}')
mapfile -t CMD  < <(docker inspect "$NAME" --format '{{range .Config.Cmd}}{{println .}}{{end}}')
[[ ${#CMD[@]} -gt 0 ]] || die "دستورِ اجرای کانتینر خوانده نشد."

# نگاشتِ نقش → Dockerfile (مثلِ node/install.sh)
case "$ROLE" in
  download)   DF="docker/download-worker.Dockerfile" ;;
  processing) DF="docker/worker.Dockerfile" ;;
  gateway)    DF="docker/gateway.Dockerfile" ;;
  *)          DF="docker/download-worker.Dockerfile" ;;
esac
[[ -f "$REPO/$DF" ]] || die "Dockerfileِ نقش پیدا نشد: $DF"

say "کشیدنِ کدِ تازه…"
cd "$REPO"
git pull -q || git pull --depth 1 -q || true   # کلونِ shallow هم pull می‌شود

say "ساختِ ایمیجِ نقش ($ROLE / $DF)…"
docker build -q -f "$DF" -t "$IMAGE" . >/dev/null

say "بازساختِ کانتینرِ نود (env/command حفظ می‌شود)…"
ENV_ARGS=(); for e in "${ENVS[@]}"; do [[ -n "$e" ]] && ENV_ARGS+=(-e "$e"); done
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --restart unless-stopped --network host \
  "${ENV_ARGS[@]}" "$IMAGE" "${CMD[@]}" >/dev/null

say "تمام ✅  نودِ «$ROLE» با کدِ تازه بالا آمد. لاگ:  docker logs -f $NAME"
