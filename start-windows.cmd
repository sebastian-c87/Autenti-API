@echo off
rem Wylacz wyswietlanie polecen; komunikaty sa ASCII dla zgodnosci konsoli.
setlocal
rem Pracuj w folderze skryptu, takze ze spacjami w sciezce.
cd /d "%~dp0"
rem Preferuj launcher Pythona dla Windows.
py -3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
if not errorlevel 1 goto use_py
rem Alternatywnie sprawdz Python dostepny w PATH.
python -c "import sys; assert sys.version_info >= (3,11)" >nul 2>&1
if errorlevel 1 goto missing_python
rem Utworz lokalne srodowisko tylko przy pierwszym starcie.
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto failed
goto install
:use_py
rem Wybierz interpreter znaleziony przez launcher.
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto failed
:install
rem Instaluj zaleznosci w srodowisku projektu.
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
rem Uruchom panel 8000 i webhook 8001; zatrzymaj przez Ctrl+C.
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto failed
exit /b 0
:missing_python
rem Pokaz wymagania i pozostaw okno otwarte.
echo Zainstaluj Python 3.11+ z python.org i zaznacz Add python.exe to PATH.
pause
exit /b 1
:failed
rem Nie kontynuuj po bledzie instalacji lub aplikacji.
echo Blad uruchomienia. Sprawdz komunikat powyzej.
pause
exit /b 1
