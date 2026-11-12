#!/usr/bin/env bash
# channel-partnership doctor: checks every dependency, installs what can be installed user-locally,
# and prints exactly what still needs the human (keys, Google sign-in). Safe to re-run.
#   doctor.sh          check + install missing user-local deps
#   doctor.sh --check  check only, change nothing
set -uo pipefail
CHECK_ONLY=0; [ "${1:-}" = "--check" ] && CHECK_ONLY=1
HOME_DIR="${CHANNEL_PARTNERSHIP_HOME:-$HOME/.channel-partnership}"
SKILLS="$HOME/.claude/skills"
ok(){ printf '  [ok]   %s\n' "$1"; }
miss(){ printf '  [MISS] %s\n' "$1"; }
todo(){ printf '  [USER] %s\n' "$1"; }

mkdir -p "$HOME_DIR"; touch "$HOME_DIR/.env"; chmod 600 "$HOME_DIR/.env"
# packaged .skill files do not always keep the executable bit; scripts are called directly
chmod +x "$(cd "$(dirname "$0")" && pwd)"/*.py "$(cd "$(dirname "$0")" && pwd)"/*.sh 2>/dev/null
set -a; . "$HOME_DIR/.env" 2>/dev/null; set +a

echo "== runtimes"
command -v uv >/dev/null && ok "uv $(uv --version | cut -d' ' -f2)" || miss "uv (curl -LsSf https://astral.sh/uv/install.sh | sh)"
command -v node >/dev/null && ok "node $(node --version)" || miss "node (install via nvm)"
command -v python3 >/dev/null && ok "python3" || miss "python3"

echo "== web scraping: wigolo (primary), last30days (recent chatter)"
if command -v npx >/dev/null && timeout 120 npx -y wigolo doctor --json 2>/dev/null | grep -q '"status":"ok"'; then ok "wigolo CLI"
else
  miss "wigolo"; [ $CHECK_ONLY = 0 ] && command -v npx >/dev/null && { npx -y wigolo init --json >/dev/null 2>&1 && ok "wigolo initialised"; }
fi
for s in wigolo last30days apify-ultimate-scraper mem0 gws-gmail gws-shared cold-email; do
  [ -f "$SKILLS/$s/SKILL.md" ] && ok "skill $s" || {
    miss "skill $s"
    if [ $CHECK_ONLY = 0 ]; then
      case $s in
        last30days) src=mvanhorn/last30days-skill@last30days;;
        apify-ultimate-scraper) src=apify/agent-skills@apify-ultimate-scraper;;
        mem0) src=mem0ai/mem0@mem0;;
        gws-gmail) src=googleworkspace/cli@gws-gmail;;
        cold-email) src=coreyhaines31/marketingskills@cold-email;;
        wigolo) (cd "$HOME" && npx -y wigolo skills add --global >/dev/null 2>&1) && ok "wigolo skills added"; continue;;
        gws-shared)  # not on skills.sh: gws generates it. Generate in a temp dir and keep only what we use.
          if command -v gws >/dev/null; then G=$(mktemp -d); (cd "$G" && gws generate-skills >/dev/null 2>&1)
            for g in gws-shared gws-gmail-send gws-gmail-read; do [ -d "$G/skills/$g" ] && [ ! -e "$SKILLS/$g" ] && cp -r "$G/skills/$g" "$SKILLS/$g"; done
            [ -f "$SKILLS/gws-shared/SKILL.md" ] && ok "generated gws-shared (+ gmail send/read)"
          fi; continue;;
        *) continue;;
      esac
      (cd "$HOME" && npx -y skills add "$src" -g -y >/dev/null 2>&1) && ok "installed $s"
      # keep ~/.claude/skills as real files (a symlink breaks when ~/.agents is cleaned)
      if [ -L "$SKILLS/$s" ]; then t=$(readlink -f "$SKILLS/$s"); rm "$SKILLS/$s" && cp -rL "$t" "$SKILLS/$s"; fi
    fi
  }
done

echo "== Gmail (official gws CLI)"
if command -v gws >/dev/null; then
  ok "gws $(gws --version 2>/dev/null | head -1)"
  if gws gmail users getProfile --params '{"userId":"me"}' >/dev/null 2>&1; then ok "Gmail connected"
  else todo "Gmail not connected (optional). Ask Claude to 'connect my Gmail': it runs the guided setup (scripts/gmail_setup.py)"; fi
else
  miss "gws binary"
  if [ $CHECK_ONLY = 0 ]; then
    # official googleworkspace/cli release for this OS/CPU; checksum-verified; gh optional (curl fallback)
    arch=$(uname -m); [ "$arch" = arm64 ] && arch=aarch64
    case "$(uname -s)" in Darwin) target="${arch}-apple-darwin";; *) target="${arch}-unknown-linux-gnu";; esac
    asset="google-workspace-cli-${target}.tar.gz"; T=$(mktemp -d); mkdir -p "$HOME/.local/bin"
    if command -v gh >/dev/null && gh release download -R googleworkspace/cli -p "${asset}*" -D "$T" >/dev/null 2>&1; then :
    else
      curl -fsSL -o "$T/$asset" "https://github.com/googleworkspace/cli/releases/latest/download/$asset" \
        && curl -fsSL -o "$T/$asset.sha256" "https://github.com/googleworkspace/cli/releases/latest/download/$asset.sha256"
    fi
    if [ -f "$T/$asset" ] && (cd "$T" && { command -v sha256sum >/dev/null && sha256sum -c "$asset.sha256" || shasum -a 256 -c "$asset.sha256"; } >/dev/null 2>&1) \
       && tar xzf "$T/$asset" -C "$T"; then
      install -m755 "$(find "$T" -name gws -type f | head -1)" "$HOME/.local/bin/gws" && ok "installed gws ($target) to ~/.local/bin"
      case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) todo "add ~/.local/bin to your PATH (e.g. in ~/.bashrc or ~/.zshrc), then restart the terminal";; esac
    else miss "could not download/verify gws for $target (Gmail stays optional: drafts go to .eml files)"; fi
  fi
fi

echo "== keys (stored in $HOME_DIR/.env, chmod 600)"
[ -n "${APIFY_TOKEN:-${APIFY_API_TOKEN:-}}" ] && ok "APIFY_TOKEN" || todo "APIFY_TOKEN — console.apify.com/settings/integrations (free plan = \$5/month credit)"
echo "== brain: self-hosted mem0 (no key, no cloud) + claude-code-mem0 plugin"
D="$(cd "$(dirname "$0")" && pwd)"; SKILL_DIR="$(dirname "$D")"
PLUG_HOME="$HOME/.claude/local-plugins"; PLUG="$PLUG_HOME/claude-code-mem0"
WS="${CHANNEL_PARTNERSHIP_WORKSPACE:-$HOME/channel-partnership-workspace}"
if [ $CHECK_ONLY = 0 ]; then
  # 1. the patched plugin ships inside this skill (assets/); install/refresh it, keep localmem.py identical
  mkdir -p "$PLUG_HOME/.claude-plugin"
  # shipped as a tarball so the plugin's own SKILL.md files are never loaded as nested skills of this one
  T=$(mktemp -d); tar xzf "$SKILL_DIR/assets/claude-code-mem0.tar.gz" -C "$T"
  if [ ! -f "$PLUG/hooks/localmem.py" ] || ! diff -rq "$T/claude-code-mem0" "$PLUG" -x .git -x __pycache__ -x .pytest_cache -x localmem.py >/dev/null 2>&1; then
    mkdir -p "$PLUG" && cp -r "$T/claude-code-mem0/." "$PLUG/" && ok "installed patched mem0 plugin to $PLUG"
  fi
  cp "$D/localmem.py" "$PLUG/hooks/localmem.py"
  [ -f "$PLUG_HOME/.claude-plugin/marketplace.json" ] || cp "$SKILL_DIR/assets/marketplace.json" "$PLUG_HOME/.claude-plugin/marketplace.json"
  MKT=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['name'])" "$PLUG_HOME/.claude-plugin/marketplace.json")
  # 2. dedicated workspace: the plugin is enabled ONLY here, so other projects' prompts never enter the brain
  mkdir -p "$WS"
  [ -f "$WS/.env" ] || { printf 'MEM0_ENV_FILE=%s/.env\nMEM0_USER_ID=channel-partnership\nMEM0_TOP_K=8\n' "$HOME_DIR" > "$WS/.env"; chmod 600 "$WS/.env"; }
  if ! grep -q '"mem0@' "$WS/.claude/settings.json" 2>/dev/null; then
    if command -v claude >/dev/null; then
      (cd "$WS" && claude plugin marketplace add "$PLUG_HOME" --scope project >/dev/null 2>&1 \
        && claude plugin install "mem0@$MKT" --scope project >/dev/null 2>&1) && ok "mem0 plugin enabled in $WS"
    else todo "claude CLI not on PATH: in $WS run  claude plugin marketplace add $PLUG_HOME --scope project && claude plugin install mem0@$MKT --scope project"; fi
  fi
  # 3. initialise the store + download the embedding model once (65 MB), then mirror every campaign's ledger
  if command -v uv >/dev/null; then
    uv run --quiet --no-project --python 3.12 --with 'mem0ai>=2,<3' --with fastembed python3 -c \
      "import sys;sys.path.insert(0,'$D');import localmem;sys.exit(0 if localmem.open_memory(30) else 1)" >/dev/null 2>&1 \
      && ok "local mem0 store ready" || miss "local mem0 store failed to initialise (run again; check disk space)"
    for c in "$HOME_DIR"/*/; do n=$(basename "$c"); [ "$n" = mem0 ] || [ "$n" = _operator ] && continue
      [ -d "$c/brain" ] && "$D/brain.py" sync-mem0 "$n" >/dev/null 2>&1 && ok "synced campaign '$n' into mem0"; done
  fi
fi
[ -d "$HOME_DIR/mem0/qdrant" ] && ok "local mem0 store $(du -sh "$HOME_DIR/mem0" | cut -f1) at $HOME_DIR/mem0" || miss "local mem0 store"
cmp -s "$PLUG/hooks/localmem.py" "$D/localmem.py" 2>/dev/null && ok "mem0 plugin shares the brain store" || miss "mem0 plugin (run doctor.sh without --check)"
grep -q '"mem0@' "$WS/.claude/settings.json" 2>/dev/null && ok "plugin enabled in workspace: cd $WS && claude" || miss "plugin not enabled in $WS"

echo "== python deps (resolved per-script by uv; first run downloads them)"
if [ $CHECK_ONLY = 0 ] && command -v uv >/dev/null; then
  uv run --quiet --script "$D/brain.py" -h >/dev/null 2>&1 && ok "brain.py (mem0ai)" || miss "brain.py deps"
  uv run --quiet --script "$D/prospects.py" -h >/dev/null 2>&1 && ok "prospects.py (dnspython)" || miss "prospects.py deps"
  uv run --quiet --script "$D/review.py" -h >/dev/null 2>&1 && ok "review.py (openpyxl: review sheet)" || miss "review.py deps"
  for x in evidence render apify_run gmail gmail_setup diff_learn; do "$D/$x.py" -h >/dev/null 2>&1 || miss "$x.py"; done
fi
echo "== data dir: $HOME_DIR"
for c in "$HOME_DIR"/*/; do n=$(basename "$c"); case $n in mem0|_operator) ;; *) echo "  campaign: $n";; esac; done
