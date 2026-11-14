# Conduit on AWS — Runbook

Copy-paste steps for running the gateway on one EC2 instance, reachable publicly only through Tailscale Funnel, with models served by Ollama on your Mac. The reasoning behind every choice is in the design doc (`docs/superpowers/specs/2026-11-13-aws-deployment-design.md`, local only). This file is just the how.

> **Status: untested.** Written before the first deployment. Steps marked **[verify]** depend on current AWS/Tailscale behaviour; when one turns out different, fix it here. Prices are approximate.

Placeholders used below: `<mac-ip>` = your Mac's Tailscale IP (`100.x.y.z`); `<gw>` = the EC2 machine's name in Tailscale (e.g. `conduit-gateway`); `<tailnet>` = your tailnet's `.ts.net` name.

---

## 0. Before you start

- [ ] AWS account with **MFA on the root user**, and an everyday IAM/Identity Center user for the console.
- [ ] **Billing alerts first** (§1), before creating any resource.
- [ ] Tailscale account; the Mac has the Tailscale app installed and signed in; Funnel confirmed available.
- [ ] The three models pulled on the Mac: `ollama pull qwen3.5:9b qwen3.5:4b gemma4:e4b` (one per command if your Ollama version wants it).
- [ ] This repo on your Mac (you will copy it to the instance in §5).

## 1. Budget alerts (AWS console, root or a billing-enabled user)

Billing and Cost Management → Budgets → Create budget → *Cost budget*, monthly, fixed amount. Make three: **$25**, **$50**, **$80**, each emailing you at 100% of actual spend (also add an alert at 100% *forecasted* on the $50 one). **[verify]** that your user can see Billing (IAM users need billing access turned on by the root user).

## 2. Tailscale policy (do this *before* the instance joins)

In the Tailscale admin console → **Access controls**, replace the default allow-everything rule with the policy below. This is the most important security step: the EC2 machine will be internet-facing, so it must only be able to reach Ollama on your Mac.

Find `<mac-ip>` in the admin console's Machines page.

```jsonc
{
  "tagOwners": {
    "tag:conduit-gateway": ["autogroup:admin"]
  },

  // Friendly name for your Mac so rules read clearly.
  "hosts": {
    "conduit-mac": "<mac-ip>"
  },

  "acls": [
    // Your own devices can reach everything (including the instance, for SSH/tunnels).
    {"action": "accept", "src": ["autogroup:member"], "dst": ["*:*"]},
    // The internet-facing instance may reach ONLY Ollama on the Mac. Nothing else.
    {"action": "accept", "src": ["tag:conduit-gateway"], "dst": ["conduit-mac:11434"]}
  ],

  // Allow Tailscale SSH from your devices to the instance, as the 'ubuntu' user.
  "ssh": [
    {"action": "accept", "src": ["autogroup:member"], "dst": ["tag:conduit-gateway"], "users": ["ubuntu"]}
  ],

  // Only the gateway machine may publish to the public internet via Funnel.
  "nodeAttrs": [
    {"target": ["tag:conduit-gateway"], "attr": ["funnel"]}
  ],

  // Tailscale refuses to save the policy if these don't hold.
  "tests": [
    {"src": "tag:conduit-gateway", "accept": ["conduit-mac:11434"], "deny": ["conduit-mac:22", "conduit-mac:8000"]}
  ]
}
```

**[verify]** the exact syntax in the admin console's policy editor (it validates as you type). Also on the **DNS** page: MagicDNS **on**, and **HTTPS certificates enabled**.

## 3. Expose Ollama to the tailnet (on the Mac)

Keep Ollama listening on loopback only (the default; don't set `OLLAMA_HOST=0.0.0.0`, that exposes it to your Wi-Fi). Publish it to the tailnet through Tailscale instead:

```sh
# macOS: the CLI lives inside the app; alias it for this session
alias tailscale=/Applications/Tailscale.app/Contents/MacOS/Tailscale
tailscale serve --bg --tcp 11434 tcp://localhost:11434     # [verify syntax]
tailscale serve status
```

Check from the Mac itself: `curl http://<mac-ip>:11434/api/tags` lists your models.

## 4. Launch the EC2 instance (AWS console)

1. **IAM → Roles → Create role** → trusted entity *EC2* → attach `AmazonSSMManagedInstanceCore` → name it `conduit-ec2-ssm`. (This is only so you have a backup way in if Tailscale breaks.)
2. **EC2 → Launch instance**:
   - Name: `conduit-gateway`
   - AMI: **Ubuntu Server 24.04 LTS**, architecture **x86_64**
   - Type: **t3.medium**
   - Key pair: **Proceed without a key pair** (you will use Tailscale SSH / SSM).
   - Network settings → Edit: create a new security group; **delete every inbound rule** (the console proposes SSH from anywhere: remove it). Leave "Auto-assign public IP" **enabled** (the instance needs outbound internet).
   - Storage: **30 GiB gp3**.
   - Advanced details: IAM instance profile `conduit-ec2-ssm`; *Shutdown behavior* **Stop**; *Termination protection* **Enable**; *Metadata version* **V2 only** **[verify field names]**.
3. Launch. Wait for "2/2 checks passed".

Confirm the security group really has **zero inbound rules** (EC2 → Security Groups → Inbound rules tab).

## 5. First login and install (via SSM Session Manager)

EC2 → select the instance → **Connect** → *Session Manager* → Connect. Then:

```sh
sudo -i
apt-get update && apt-get -y upgrade

# --- Docker (official repository, current Compose) ---
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
usermod -aG docker ubuntu
docker compose version      # must be v2.24 or newer (the prod override uses !override / !reset)

# --- Tailscale (official install script) ---
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --ssh --advertise-tags=tag:conduit-gateway --hostname=conduit-gateway
# It prints a login URL: open it in your browser and approve the machine.
```

In the Tailscale console, confirm the machine shows tag `tag:conduit-gateway`. From now on, connect from your Mac with `ssh ubuntu@conduit-gateway` (Tailscale SSH). Keep SSM as the backup.

**Check the ACL works:** on the instance:

```sh
curl -s -m 5 http://<mac-ip>:11434/api/tags | head -c 200     # should list models
curl -s -m 5 http://<mac-ip>:22 ; echo "exit=$?"                # should time out / be refused
```

## 6. Put the code and secrets on the instance

From your **Mac**, in the repo root (copies code only; never `.env`, `.git`, or the venv):

```sh
rsync -az --delete \
  --exclude .env --exclude .venv --exclude .git --exclude docs --exclude __pycache__ \
  ./ ubuntu@conduit-gateway:~/conduit/
```

On the **instance** (`ssh ubuntu@conduit-gateway`), create `.env` with fresh random secrets. Nothing secret appears on the command line or in shell history because the values are generated inside the file:

```sh
cd ~/conduit
umask 077
cat > .env <<EOF
ADMIN_API_KEY=$(openssl rand -hex 32)
GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 24)
OPENAI_API_KEY=not-configured
ANTHROPIC_API_KEY=not-configured
GEMINI_API_KEY=not-configured
OLLAMA_BASE_URL=http://<mac-ip>:11434
EOF
ls -l .env        # must show -rw------- (600)
```

Notes: the gateway requires all three provider keys to be *set* or it crashes at startup, hence the placeholders. Use the Mac's tailnet **IP** in `OLLAMA_BASE_URL`, not its `.ts.net` name: containers don't reliably inherit Tailscale's DNS. No paid provider is configured on purpose (no API spend possible, no provider secrets on a public-facing machine).

## 7. Start the stack

```sh
cd ~/conduit
docker compose --env-file .env \
  -f infra/docker-compose.yaml -f infra/docker-compose.prod.yaml \
  up -d --build
docker compose --env-file .env -f infra/docker-compose.yaml -f infra/docker-compose.prod.yaml ps
```

Expected: gateway, postgres, redis, prometheus, grafana, otel-collector, tempo, nginx all `running`. The `dummy`, `seed` and `locust` profiles are **not** started, which is what you want. **Never run the `seed` profile here** (it creates guessable team keys).

Check memory headroom once: `docker stats --no-stream` and `free -m` (if the instance is short of RAM, move to `t3.large`).

Local smoke test on the instance:

```sh
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/api/v1/models   # 422 (no key) = alive through nginx
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/admin/ui         # 404 = admin blocked at the front door
```

## 8. Publish with Funnel

```sh
sudo tailscale funnel --bg 8080        # [verify syntax]
tailscale funnel status                # shows https://conduit-gateway.<tailnet>.ts.net
```

That URL is what your friend uses. Test it **from a device that is not on your tailnet** (e.g. your phone on mobile data, or ask your friend):

```sh
curl -s -o /dev/null -w "%{http_code}\n" https://conduit-gateway.<tailnet>.ts.net/admin/ui      # 404
curl -s -o /dev/null -w "%{http_code}\n" https://conduit-gateway.<tailnet>.ts.net/metrics       # 404
curl -s -o /dev/null -w "%{http_code}\n" https://conduit-gateway.<tailnet>.ts.net/api/v1/models # 422 (needs a key)
```

## 9. Configure Conduit (private admin access)

Open an SSH tunnel from your Mac (local ports 9000/3001 so they don't clash with a local gateway):

```sh
ssh -N -L 9000:127.0.0.1:8000 -L 3001:127.0.0.1:3000 ubuntu@conduit-gateway
```

- Admin page: `http://localhost:9000/admin/ui`. Admin key: on the instance run `grep ^ADMIN_API_KEY= ~/conduit/.env` and paste the value (don't paste it anywhere else).
- Grafana: `http://localhost:3001` (user `admin`, password = `GRAFANA_ADMIN_PASSWORD` from `.env`).

In the admin page:
1. **Models** → add `qwen3.5:9b` (ollama, tier 3), `qwen3.5:4b` and `gemma4:e4b` (ollama, tier 2), all $0. Names must match Ollama exactly.
2. **Teams** → create two teams for your friend, for example **"Friend – 2/min demo"** (rate limit 2) and **"Friend – 20/min"** (rate limit 20), each with the models you want them to use. Copy each key when shown; it is displayed once.

Hand your friend: the URL, the key(s) and which is which, and how to install `conduit-cli`.

## 10. Acceptance run

Run the checklist in design doc §10. Two parts are scripted:

- Front-door allowlist (from your Mac, no AWS needed): `infra/nginx/test_allowlist.sh`
- On the instance, from a non-tailnet device: the three `curl`s in §8, plus a real chat with the friend's key through the CLI.

## 11. Auto-stop (cost backstop)

Powers the instance off 8 hours after every boot. Because shutdown behaviour is *Stop*, this stops compute billing. Install once on the instance:

```sh
sudo tee /etc/systemd/system/conduit-autostop.service >/dev/null <<'EOF'
[Unit]
Description=Power off to stop AWS billing

[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl poweroff
EOF
sudo tee /etc/systemd/system/conduit-autostop.timer >/dev/null <<'EOF'
[Unit]
Description=Auto power-off 8 hours after boot

[Timer]
OnBootSec=8h
Unit=conduit-autostop.service

[Install]
WantedBy=timers.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now conduit-autostop.timer
systemctl list-timers conduit-autostop.timer     # shows when it will fire
```

- **Test it once** with `OnBootSec=3min` (edit the timer, `daemon-reload`, reboot) and confirm the instance shows *Stopped* in the console. Then set it back to `8h`.
- **Extend a session:** `sudo systemctl stop conduit-autostop.timer; sudo systemd-run --on-active=4h systemctl poweroff`
- **Cancel it** (e.g. for a long demo): `sudo systemctl stop conduit-autostop.timer`

## 12. Every session

**Start:** EC2 console → select instance → Instance state → *Start* (or `aws ec2 start-instances --instance-ids <id>`). Wait ~2 minutes. Make sure your Mac is awake, plugged in, Ollama running, and a model loaded (`ollama run qwen3.5:4b` then `/bye`, so the first request isn't slow). Containers and Funnel come back by themselves; the URL and keys are unchanged. Run one chat through the CLI to confirm.

**Stop:** EC2 console → Instance state → *Stop* (not *Terminate*). Stopped = no compute charge; the 30 GB disk (~$2.40/month) still bills.

**Update the code:** rsync as in §6, then `docker compose … up -d --build` as in §7.

## 13. Troubleshooting

| Symptom | Check |
|---|---|
| Friend gets a connection/502 error | Is the instance running? `tailscale funnel status` on it. `docker compose … ps`. |
| Chat fails with a provider/connection error | Is the Mac awake with Ollama running? On the instance: `curl -m 5 http://<mac-ip>:11434/api/tags`. |
| That `curl` works on the instance but the gateway still fails | Test from inside the container: `docker compose … exec gateway python -c "import urllib.request;print(urllib.request.urlopen('http://<mac-ip>:11434/api/tags',timeout=5).status)"`. If it fails, the container can't route to the tailnet: tell me (fallback: host networking for the gateway). |
| Containers didn't come back after a start | `systemctl status docker`; `docker compose … ps -a`; confirm `restart: unless-stopped` in the prod override. |
| `docker compose` complains about `!override`/`!reset` | Compose is too old: `docker compose version` must be ≥ 2.24. |
| `docker compose` complains `GRAFANA_ADMIN_PASSWORD` is unset | You forgot `--env-file .env`. |
| Can't SSH | Tailscale up on both ends? ACL `ssh` rule present? Fall back to SSM (§5). |
| Admin page says wrong key | The gateway uses `ADMIN_API_KEY` from the instance's `.env`; restart the gateway after changing it. |

## 14. Teardown (end of project)

1. EC2 → disable termination protection → **Terminate** the instance (this deletes the root volume if "delete on termination" was left on **[verify]**).
2. EC2 → Volumes and Snapshots: make sure nothing is left behind. Delete the security group and the `conduit-ec2-ssm` role.
3. Tailscale console: remove the `conduit-gateway` machine; remove the `tag:conduit-gateway` rules, and the `tailscale serve` entry on the Mac (`tailscale serve reset`).
4. Delete the three Budgets (or keep one as a safety net).
5. Look at the AWS billing page the next day and the day after; it should show nothing running.
