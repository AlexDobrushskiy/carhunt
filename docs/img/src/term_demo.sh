#!/bin/zsh
export CARHUNT_HOME=/private/tmp/carhunt-screens/home CARHUNT_CONFIG=/private/tmp/carhunt-screens/home/config.yaml PATH=/private/tmp/carhunt-screens/bin:/opt/homebrew/bin:/usr/bin:/bin CARHUNT_FAKE_SITES=1
cd /private/tmp/carhunt-screens/home
rm -f discover/cursors.json discover/seen.json
p() { printf '\033[1;32m$\033[0m %s\n' "$1"; }
clear
p "carhunt sweep --sites fake --max 6"; carhunt sweep --sites fake --max 6 2>&1 | grep -v "^sweep:"
echo; p "cardb queue --limit 8"; cardb queue --limit 8
echo; p "carhunt say --channel whatsapp --car 18 --opener --dry-run --text \"Olá! O Enyaq ainda está disponível?\""
carhunt say --channel whatsapp --car 18 --opener --dry-run --text "Olá! O Enyaq ainda está disponível?" 2>&1 | head -6
printf '\033[1;32m$\033[0m '; sleep 3600
