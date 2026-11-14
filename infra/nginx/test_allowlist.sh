#!/usr/bin/env bash
# Verifies the nginx allowlist in conduit.conf against a stub gateway, in Docker.
# Usage: infra/nginx/test_allowlist.sh        (needs docker; pulls two small images)
# Exits non-zero if any path/method behaves differently from the allowlist.
set -u
cd "$(dirname "$0")"
NET=conduit-ngtest; PORT=18080; fail=0
cleanup() { docker rm -f ngtest-gateway ngtest-nginx >/dev/null 2>&1; docker network rm $NET >/dev/null 2>&1; }
trap cleanup EXIT; cleanup
docker network create $NET >/dev/null
docker run -d --rm --name ngtest-gateway --network-alias gateway --network $NET python:3.12-slim python -c "
from http.server import *
class H(BaseHTTPRequestHandler):
    def _r(self):
        n=int(self.headers.get('content-length') or 0); self.rfile.read(n)
        self.send_response(200); self.send_header('content-length','2'); self.end_headers(); self.wfile.write(b'ok')
    do_GET=do_POST=do_PUT=do_PATCH=do_DELETE=_r
ThreadingHTTPServer(('0.0.0.0',8000),H).serve_forever()" >/dev/null
docker run -d --rm --name ngtest-nginx --network $NET -p 127.0.0.1:$PORT:8080 \
  -v "$PWD/conduit.conf:/etc/nginx/conf.d/default.conf:ro" nginx:stable-alpine >/dev/null
sleep 3
check() { # method path expected [curl args...]
  local got; got=$(curl -s -o /dev/null -w "%{http_code}" -X "$1" "http://127.0.0.1:$PORT$2" "${@:4}")
  if [ "$got" = "$3" ]; then echo "ok    $1 $2 -> $got"; else echo "FAIL  $1 $2 -> $got (expected $3)"; fail=1; fi
}
check POST /api/v1/chat/completion 200 -d '{}'
check GET  /api/v1/models 200
check GET  /api/v1/chat/completion 403
check POST /api/v1/models 403
for p in /admin/ui /admin/v1/teams /metrics /docs /redoc /openapi.json / /api/v1/models/ \
         /api/v1/models/../../admin/ui //admin/ui "/api/v1/models%2f..%2fadmin" /api/v1/chat/completion/x; do
  check GET "$p" 404; done
check POST /admin/v1/teams 404 -d '{}'
check DELETE /admin/v1/teams/x 404
big=$(head -c 300000 /dev/zero | tr '\0' a)
got=$(printf %s "$big" | curl -s -o /dev/null -w "%{http_code}" -X POST --data-binary @- "http://127.0.0.1:$PORT/api/v1/chat/completion")
[ "$got" = 413 ] && echo "ok    300KB body -> 413" || { echo "FAIL  300KB body -> $got (expected 413)"; fail=1; }
sleep 2
n=$(seq 200 | xargs -P 50 -I{} curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:$PORT/api/v1/models" | grep -c 429)
[ "$n" -gt 0 ] && echo "ok    burst of 200 -> $n x 429" || { echo "FAIL  burst of 200 produced no 429"; fail=1; }
[ $fail = 0 ] && echo "ALL OK" || echo "FAILURES"; exit $fail
