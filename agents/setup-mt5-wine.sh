#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# MetaTrader 5 on Linux (headless-ready) — for the MT5 Web Console
#
# Verified facts this script is built around (Sept 2026):
#  * MetaQuotes publishes NO native Linux build. The official
#    https://download.terminal.free/cdn/web/metaquotes.software.corp/mt5/mt5linux.sh
#    installer is a *Wine bootstrap*: it apt-installs winehq-staging, then runs
#    the Windows mt5setup.exe inside a Wine prefix (~/.mt5), and needs sudo + the
#    graphical installer wizard. (same info: metatrader5.com/en/terminal/help/start_advanced/install_linux)
#  * The PyPI project 'MetaTrader5' ships ONLY win_amd64 wheels
#    (e.g. metatrader5-5.0.6180-cp311-cp311-win_amd64.whl) and its _core.pyd is a
#    Windows PE binary -> `pip install MetaTrader5` can never work under native
#    Linux python. Proof:
#       $ pip download MetaTrader5
#       ERROR: No matching distribution found for MetaTrader5
#
# What we do here: install Wine (+ Xvfb for a headless display), install MT5 into
# ~/.mt5, and leave the terminal running under xvfb-run so the Bridge agent can
# attach to it. Optional --with-wine-python also sets up a Windows python inside
# the same prefix, so the agent itself can run on this Linux box.
# ---------------------------------------------------------------------------
set -Eeuo pipefail

PREFIX="${WINEPREFIX:-$HOME/.mt5}"
MT5_DIR="$PREFIX/drive_c/Program Files/MetaTrader 5"
MT5_URL="https://download.terminal.free/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
OFFICIAL_SH="https://download.terminal.free/cdn/web/metaquotes.software.corp/mt5/mt5linux.sh"
APPDATA_URL="https://download.terminal.free/cdn/web/metaquotes.software.corp/mt5/mt5Portable.zip"
SUDO=""
WITH_WINE_PY=0
PORTABLE=0
RUN_NOW=0
STATUS_ONLY=0
USE_OFFICIAL=1
USE_SUDO=1

log() { printf '\n\033[1;36m[mt5-linux]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[mt5-linux] warn:\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[mt5-linux] error:\033[0m %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-sudo)        USE_SUDO=0; shift ;;
    --wine-python)    WITH_WINE_PY=1; shift ;;
    --portable)       PORTABLE=1; shift ;;
    --run)            RUN_NOW=1; shift ;;
    --status)         STATUS_ONLY=1; shift ;;
    --no-official)    USE_OFFICIAL=0; shift ;;
    -h|--help)        sed -n '2,40p' "$0"; exit 0 ;;
    *) die "unknown flag: $1 (try --help)" ;;
  esac
done

if [[ $EUID -eq 0 ]]; then
  warn "running as root: Wine must run as your normal user. Re-run without sudo."
  exit 1
fi
SUDO=""
if [[ $USE_SUDO -eq 1 ]]; then
  if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    SUDO="sudo"
  elif command -v sudo >/dev/null 2>&1; then
    warn "sudo exists but needs a password - re-run and type it when asked, or use --no-sudo"
    SUDO="sudo"
  fi
fi
apt_check() {
  # fail fast with an actionable message instead of a lock-file stack trace
  if [[ -n $SUDO ]]; then
    $SUDO -n true 2>/dev/null || die "cannot run '$SUDO -n true' - this environment has no usable sudo (Render services do not). Pass --no-sudo to skip system installs and only configure an already-present Wine."
  fi
  if [[ -f /var/lib/apt/lists/lock ]] && ! $SUDO test -w /var/lib/apt/lists/ 2>/dev/null; then
    die "apt lists are not writable (missing privileges or another apt is running). Re-run with sudo, or --no-sudo if Wine is already installed."
  fi
}

# --------------------------------------------------------------------------- #
have() { command -v "$1" >/dev/null 2>&1; }

status() {
  log "status"
  printf '  wine            : %s\n' "$(have wine && wine --version 2>/dev/null || echo 'NOT installed')"
  printf '  Xvfb (headless)  : %s\n' "$(have Xvfb && echo present || echo 'NOT installed')"
  printf '  winetricks       : %s\n' "$(have winetricks && echo present || echo 'NOT installed')"
  printf '  Wine prefix      : %s (%s)\n' "$PREFIX" "$([[ -d $PREFIX ]] && echo exists || echo missing)"
  printf '  MT5 terminal     : %s\n' "$([[ -f "$MT5_DIR/terminal64.exe" ]] && echo "installed -> $MT5_DIR" || echo 'not installed')"
  printf '  wine python      : %s\n' "$([[ -f "$PREFIX/drive_c/Python312/python.exe" ]] && echo present || echo 'not installed')"
  printf '  native mt5 pkg   : %s\n' "$(python3 -c 'import MetaTrader5' 2>/dev/null && echo importable || echo 'no (impossible on Linux - Windows wheels only)')"
}
if [[ $STATUS_ONLY -eq 1 ]]; then status; exit 0; fi

# --------------------------------------------------------------------------- #
log "preflight"
. /etc/os-release 2>/dev/null || warn "/etc/os-release not found; assuming apt-based distro"
ID="${ID:-debian}"
case "$ID" in
  ubuntu|debian|linuxmint|pop)
    have apt-get || die "apt-get not found but ID=$ID"
    PKG="apt" ;;
  fedora|rhel|centos)
    PKG="dnf" ;;
  *)
    warn "untested distro '$ID' - continuing with apt if present"
    PKG="apt" ;;
esac
log "package manager: $PKG ; sudo: ${SUDO:-<none>}"

# --------------------------------------------------------------------------- #
if ! have wine; then
  if [[ $USE_OFFICIAL -eq 1 && $PKG == apt ]]; then
    log "trying the official MetaQuotes bootstrap (mt5linux.sh)"
    TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
    if curl -fsSL "$OFFICIAL_SH" -o "$TMP/mt5linux.sh"; then
      chmod +x "$TMP/mt5linux.sh"
      warn "the official script needs sudo and clicks in the MT5 installer wizard"
      warn "if you are on a headless server, re-run this script with --no-official --portable"
      "$TMP/mt5linux.sh" || warn "official script failed/aborted - falling back to the manual path"
    else
      warn "could not download the official script (blocked network?) - using the manual path"
    fi
  fi
fi

if ! have wine; then
  if [[ -z $SUDO ]]; then
    die "wine is not installed and --no-sudo was given: nothing can be installed. Either run this with working sudo on your own Linux box, or keep the terminal on Windows and only run the bridge agent."
  fi
  log "installing Wine ${WINE_VERSION:-staging} + Xvfb + winetricks"
  if [[ $PKG == apt ]]; then
    apt_check
    $SUDO apt-get update -y
    $SUDO apt-get install -y --no-install-recommends wget curl ca-certificates gnupg \
      xauth xvfb winetricks cabextract unzip 2>/dev/null || true
    $SUDO dpkg --add-architecture i386
    $SUDO mkdir -pm755 /etc/apt/keyrings
    if ! curl -fsSL https://dl.winehq.org/wine-builds/winehq.key \
      | $SUDO tee /etc/apt/keyrings/winehq-archive.key >/dev/null; then
      die "cannot reach dl.winehq.org (TLS/DNS blocked or offline sandbox). On Render you have neither sudo nor this domain - install Wine on a real Linux host instead."
    fi
    case "${VERSION_ID:-12}" in
      24.*|25.*) REPO=questing; REPO=plucky ;;   # ubuntu 24.04/24.10/25.04 -> noble/plucky
      22.*)     REPO=jammy ;;
      20.*)     REPO=focal ;;
      13)       REPO=trixie ;;
      *)        REPO=bookworm ;;
    esac
    case "$ID" in
      ubuntu) URL="https://dl.winehq.org/wine-builds/ubuntu/dists/${REPO}/winehq-${REPO}.sources" ;;
      *)      URL="https://dl.winehq.org/wine-builds/debian/dists/${REPO}/winehq-${REPO}.sources" ;;
    esac
    if ! curl -fsSL -o /tmp/winehq.sources "$URL"; then
      die "cannot fetch the WineHQ repo file ($URL). Network blocked? On Render you also lack sudo - install on your own box."
    fi
    $SUDO cp /tmp/winehq.sources /etc/apt/sources.list.d/
    $SUDO apt-get update -y
    $SUDO apt-get install -y --install-recommends "winehq-${WINE_VERSION:-staging}" \
      || die "apt install winehq-staging failed - see the notes about Render (no sudo / no display)"
  else
    $SUDO dnf install -y xorg-x11-server-Xvfb winetricks cabextract unzip
    $SUDO dnf config-manager addrepo --from-repofile="https://dl.winehq.org/wine-builds/fedora/41/winehq.repo" || true
    $SUDO dnf install -y "winehq-${WINE_VERSION:-staging}" || die "dnf install wine failed"
  fi
fi
have wine || die "wine is still missing"
log "wine: $(wine --version)"

# --------------------------------------------------------------------------- #
log "preparing Wine prefix at $PREFIX (win11)"
mkdir -p "$PREFIX"
WINEPREFIX="$PREFIX" winecfg -v=win11 >/dev/null 2>&1 || true
log "installing Wine dependencies the terminal expects (fonts, vcrun)"
WINEPREFIX="$PREFIX" WINEDLLOVERRIDES="mscoree,mshtml=" winetricks -q corefonts vcrun2022 dotnet48 2>/dev/null \
  || WINEPREFIX="$PREFIX" winetricks -q corefonts vcrun2022 2>/dev/null \
  || warn "winetricks step failed (often a download block). MT5 may still work; check --status."

# --------------------------------------------------------------------------- #
if [[ ! -f "$MT5_DIR/terminal64.exe" ]]; then
  log "downloading MetaTrader 5 installer"
  TMPDL="$(mktemp -d)"; trap 'rm -rf "$TMPDL"' EXIT
  if ! curl -fL --retry 3 -o "$TMPDL/mt5setup.exe" "$MT5_URL"; then
    die "download of $MT5_URL failed. This sandbox/network blocks it - run this script on a box with open egress."
  fi
  size=$(wc -c < "$TMPDL/mt5setup.exe")
  head -c2 "$TMPDL/mt5setup.exe" | grep -q MZ || die "downloaded file is not a Windows PE binary ($size bytes)"
  log "got mt5setup.exe ($size bytes, Windows PE) - installing into the prefix"
  if [[ $PORTABLE -eq 1 ]]; then
    WINEPREFIX="$PREFIX" wine "$TMPDL/mt5setup.exe" /auto || warn "/auto silent flag failed; retrying interactive"
  fi
  WINEPREFIX="$PREFIX" wine "$TMPDL/mt5setup.exe" || die "MT5 installer exited non-zero (a display is needed: prefix it with 'xvfb-run -a -s \"-screen 0 1440x900x24\"')"
else
  log "MT5 already installed at $MT5_DIR - skipping install"
fi
[[ -f "$MT5_DIR/terminal64.exe" ]] || die "terminal64.exe not found after install"

# --------------------------------------------------------------------------- #
if [[ $WITH_WINE_PY -eq 1 && ! -f "$PREFIX/drive_c/Python312/python.exe" ]]; then
  log "installing a *Windows* python into the prefix (so the agent can use MetaTrader5 here)"
  TMPDL="$(mktemp -d)"; trap 'rm -rf "$TMPDL"' EXIT
  curl -fL -o "$TMPDL/py.exe" "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" \
    || warn "python installer download blocked - skip with --no-flag and use a Windows box instead"
  if [[ -f "$TMPDL/py.exe" ]]; then
    WINEPREFIX="$PREFIX" wine "$TMPDL/py.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 \
      TargetDir='C:\Python312' || warn "wine python install failed"
    WINEPREFIX="$PREFIX" wine 'C:\Python312\python.exe' -m pip install --upgrade pip MetaTrader5 websockets \
      || warn "pip install inside wine failed - retry manually: WINEPREFIX=$PREFIX wine C:\\Python312\\python.exe -m pip install MetaTrader5 websockets"
  fi
fi

# --------------------------------------------------------------------------- #
log "writing launcher"
cat > "$HOME/start-mt5-headless.sh" <<EOF
#!/usr/bin/env bash
# starts MetaTrader 5 on a virtual display, then (optionally) the bridge agent
export WINEPREFIX="$PREFIX"
NUM="\${DISPLAY_NUM:-99}"
NUM="\${NUM//[^0-9]/}"; NUM="\${NUM:-99}"
if [[ -z "\${DISPLAY:-}" ]] && command -v Xvfb >/dev/null; then
  nohup Xvfb ":\$NUM" -screen 0 1440x900x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
  export DISPLAY=":\$NUM"
  sleep 2
fi
MT5_EXE="$MT5_DIR/terminal64.exe"
FLAGS=""
[[ "\${1:-}" == "--portable" ]] && FLAGS="/portable"
"\$MT5_EXE" \$FLAGS >/tmp/mt5.log 2>&1 &
echo "[start-mt5] terminal launched (flags: \${FLAGS:-none}), display \$DISPLAY, log /tmp/mt5.log"
sleep 15
if [[ -n "\${MT5WEB_URL:-}" ]]; then
  PY="python3"
  [[ -x "$PREFIX/drive_c/Python312/python.exe" ]] && PY="wine $PREFIX/drive_c/Python312/python.exe"
  cd "$(pwd)" && \$PY agents/agent/main.py --name "\${MT5WEB_NAME:-linux-wine}"
fi
EOF
chmod +x "$HOME/start-mt5-headless.sh"

status
log "done."
cat <<'EOF'

Next steps
----------
1) start the terminal headless:      ~/start-mt5-headless.sh
2) then start the bridge agent        python3 agents/agent/main.py --url <app>/ws/agent --key <bridge key>
   (on this same Linux box, the agent needs the *wine* python: rerun with --wine-python)
3) in the web app: Settings -> MT5 account -> enter login / password / server -> save & connect

If you only want to *host* the dashboard, keep the terminal on Windows: a Render service
has no sudo, no X display and no Wine, so MT5 itself cannot live there.
EOF
