#!/usr/bin/env bash
# Download everything this project needs into this folder.
# Nothing is installed globally - all binaries live in ./bin and ./jdk.
#
# Cross-platform: works on Linux/macOS. On Windows use WSL or Git Bash.
#   The scripts auto-detect your CPU architecture (x86_64 / arm64 / armv7).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p bin jdk server logs cache data

# --- detect architecture -------------------------------------------------
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)   JDK_ARCH=x64   JDK_OS=linux   BORE_ARCH=x86_64-unknown-linux-musl ;;
  aarch64)  JDK_ARCH=aarch64 JDK_OS=linux  BORE_ARCH=aarch64-unknown-linux-musl ;;
  armv7l)   JDK_ARCH=aarch64 JDK_OS=linux  BORE_ARCH=armv7-unknown-linux-musleabi ;;
  *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac
echo "Detected: $ARCH"

# --- Paper server jar ------------------------------------------------------
# Paper 26.2 requires Java 21+; we bundle Java 25 (LTS) below.
if [ ! -f server/paper.jar ]; then
  echo "Downloading Paper server jar ..."
  # The Paper downloads service exposes a GraphQL API. We query it for the
  # latest STABLE build of the 26.2 line.
  QUERY='{"query":"{ project(key: \"paper\") { versions(first: 10, orderBy: {direction: DESC}) { edges { node { key builds(filterBy: { channels: [STABLE] }, first: 1, orderBy: { direction: DESC }) { edges { node { number download(key: \"server:default\") { name url size checksums { sha256 } } } } } } } } } }"}'
  URL="$(curl -s --max-time 30 -X POST -H 'Content-Type: application/json' \
    -d "$QUERY" https://fill.papermc.io/graphql \
    | python3 -c 'import json,sys
d=json.load(sys.stdin)
for e in d["data"]["project"]["versions"]["edges"]:
    v=e["node"]
    if v["key"].count(".")==1 and not any(x in v["key"] for x in ("rc","pre","snapshot")):
        b=v["builds"]["edges"][0]["node"]; print(b["download"]["url"]); break')"

  if [ -z "${URL:-}" ]; then
    echo "ERROR: could not resolve a Paper download URL"; exit 1
  fi
  curl -sL --fail --retry 3 -o server/paper.jar "$URL"
  echo "Saved server/paper.jar"
fi

# --- Temurin JDK 25 (LTS) ---------------------------------------------------
if [ ! -x jdk/current/bin/java ]; then
  echo "Downloading Temurin JDK 25 ($JDK_OS/$JDK_ARCH) ..."
  curl -sL --fail --retry 3 -o cache/jdk25.tar.gz \
    "https://api.adoptium.net/v3/binary/latest/25/ga/${JDK_OS}/${JDK_ARCH}/jdk/hotspot/normal/eclipse"
  tar xzf cache/jdk25.tar.gz -C jdk/
  ln -sfn "$(ls -d jdk/jdk-* | head -n1)" jdk/current
  echo "Java: $(jdk/current/bin/java -version 2>&1 | head -n1)"
fi

# --- bore tunnel (zero-config, no account) ----------------------------------
if [ ! -x bin/bore-bin ]; then
  echo "Downloading bore tunnel client ..."
  BORE_VER=v0.6.0
  curl -sL --fail --retry 3 -o cache/bore.tar.gz \
    "https://github.com/ekzhang/bore/releases/download/${BORE_VER}/bore-${BORE_VER}-${BORE_ARCH}.tar.gz"
  tar xzf cache/bore.tar.gz -C bin/
  mv "bin/bore" bin/bore-bin
  chmod +x bin/bore-bin
fi

# --- playit.gg agent (persistent address + UDP for Bedrock) -----------------
if [ ! -x bin/playit ] && [ ! -x bin/playitd ]; then
  echo "Downloading playit.gg agent ..."
  PLAYIT_VER=v1.0.11-preview1
  case "$ARCH" in
    x86_64)  PARCH=amd64 ;;
    aarch64) PARCH=aarch64 ;;
    armv7l)  PARCH=armv7 ;;
  esac
  curl -sL --fail --retry 3 -o bin/playit \
    "https://github.com/playit-cloud/playit-agent/releases/download/${PLAYIT_VER}/playit-cli-linux-${PARCH}"
  curl -sL --fail --retry 3 -o bin/playitd \
    "https://github.com/playit-cloud/playit-agent/releases/download/${PLAYIT_VER}/playit-linux-${PARCH}"
  chmod +x bin/playit bin/playitd
fi

# --- EULA -------------------------------------------------------------------
printf 'eula=true\n' > server/eula.txt

echo
echo "Setup complete. Start the server with:"
echo "  ./start.sh"
echo
echo "For a persistent public address (and Bedrock/UDP support):"
echo "  TUNNEL=playit ./start.sh"
