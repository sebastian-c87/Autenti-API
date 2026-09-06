#!/bin/bash
set -euo pipefail # Zatrzymaj po błędzie instalacji lub uruchomienia.
cd "$(dirname "$0")" # Przejdź do folderu aplikacji także przy dwukliku.
umask 077 # Prywatne pliki konfiguracyjne i dokumenty.
if ! command -v python3 >/dev/null 2>&1; then # Sprawdź interpreter.
  echo "Zainstaluj Python 3.11 lub nowszy z python.org, następnie uruchom ponownie." # Instrukcja naprawy.
  exit 1 # Bez próby startu bez Pythona.
fi # Koniec sprawdzenia.
python3 -c 'import sys; assert sys.version_info >= (3,11), "Wymagany Python 3.11+"' # Sprawdź wersję.
if [ ! -d .venv ]; then # Środowisko lokalne dla projektu.
  python3 -m venv .venv # Nie zmieniaj systemowych pakietów.
fi # Koniec inicjalizacji.
.venv/bin/python -m pip install -r requirements.txt # Zainstaluj przypięte zależności.
exec .venv/bin/python app.py # Uruchom panel i webhook; zatrzymanie Ctrl+C.
