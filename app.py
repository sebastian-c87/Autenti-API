"""Lokalny CRM 8000 + osobny odbiornik webhooków 8001; python app.py."""
import base64  # Kodowanie detached JWS.
import hashlib  # Fingerprint pliku i środowiska.
import hmac  # Porównanie tokenów CSRF.
import json  # Lokalna konfiguracja i dane.
import os  # Prywatne prawa dostępu.
import re  # Walidacja formularza.
import secrets  # Token sesji panelu.
import sqlite3  # Trwałe procesy i kolejka webhooków.
import threading  # Dwa serwery i worker.
import time  # Ponawianie odbioru dokumentu.
import uuid  # Lokalne identyfikatory.
from pathlib import Path  # Lokalne ścieżki.
from urllib.parse import urlsplit, urlencode  # Kontrola adresów i parametry OAuth.
from io import BytesIO  # Pobieranie PDF.
import jwt  # Weryfikacja podpisów webhooka.
import requests  # Klucze JWKS z ustalonego hosta.
from flask import Flask, request, jsonify, render_template, send_file, abort  # Panel i REST.
from werkzeug.serving import make_server, WSGIRequestHandler  # Lokalny serwer bez debuggera.
from autenti import Autenti, ApiError, BASES, JWKS, payload  # Adapter Autenti.
from documents import make_pdf  # Szablon PDF.

ROOT = Path(__file__).resolve().parent  # Katalog aplikacji.
DATA = ROOT / "data"  # Pliki prywatne, pomijane przez Git.
CONFIG = ROOT / "config.local.json"  # Sekrety pozostają na Macu.
DEFAULT = json.loads((ROOT / "config.example.json").read_text())  # Domyślne wartości.
SECRET_FIELDS = {"client_secret", "access_token", "api_key", "refresh_token", "management_token"}  # Nigdy nie odsyłaj ich w API panelu.
LOCK = threading.RLock()  # Serializacja konfiguracji i operacji.
CSRF = secrets.token_urlsafe(32)  # Token generowany po każdym uruchomieniu.
PENDING_AUTH = {}  # Jednorazowe state OAuth z terminem ważności.
admin = Flask(__name__)  # Panel lokalny.
hook = Flask("webhook")  # Brak panelu i plików na porcie ngrok.
admin.config["MAX_CONTENT_LENGTH"] = 1_000_000  # Limit formularza.
hook.config["MAX_CONTENT_LENGTH"] = 1_000_000  # Limit webhooka.

def init():  # Przygotowanie prywatnej bazy.
    DATA.mkdir(exist_ok=True, mode=0o700)  # Katalog tylko dla właściciela.
    os.chmod(DATA, 0o700)  # Także po wcześniejszym utworzeniu.
    with db() as connection:  # Transakcja migracji.
        connection.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL)")  # Procesy lokalne.
        connection.execute("CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, body TEXT NOT NULL, done INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0, next_try REAL DEFAULT 0)")  # Trwała kolejka.
    os.chmod(DATA / "crm.sqlite", 0o600)  # Dane nie są publiczne.

def db():  # Oddzielne połączenie dla wątku.
    return sqlite3.connect(DATA / "crm.sqlite", timeout=20)  # SQLite bez współdzielenia obiektów.

def config():  # Odczyt atomowo zapisywanej konfiguracji.
    return DEFAULT | (json.loads(CONFIG.read_text()) if CONFIG.exists() else {})  # Brak wymogu edycji ręcznej.

def save_config(values):  # Zapis sekretów z prawami 0600.
    with LOCK:  # Nie zgub rotowanego refresh tokenu.
        merged = config() | values  # Zachowaj pozostałe pola.
        temporary = CONFIG.with_suffix(".tmp")  # Plik pomocniczy na tym samym dysku.
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # Prywatny od początku.
        with os.fdopen(fd, "w") as target: json.dump(merged, target, ensure_ascii=False, indent=2)  # Zapis JSON.
        temporary.replace(CONFIG)  # Atomowa podmiana.
        os.chmod(CONFIG, 0o600)  # Właściwe uprawnienia.

def save_job(job):  # Zapis po każdym etapie wywołania API.
    with db() as connection: connection.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?)", (job["id"], json.dumps(job, ensure_ascii=False)))  # Parametry SQL.

def get_job(identifier):  # Tylko lokalnie znane zlecenia.
    with db() as connection: row = connection.execute("SELECT data FROM jobs WHERE id=?", (identifier,)).fetchone()  # Bez interpolacji SQL.
    if not row: abort(404)  # Nie ujawniaj innych procesów.
    return json.loads(row[0])  # Obiekt procesu.

def all_jobs():  # Historia panelu.
    with db() as connection: rows = connection.execute("SELECT data FROM jobs ORDER BY rowid DESC").fetchall()  # Najnowsze na górze.
    return [json.loads(row[0]) for row in rows]  # Lista procesów.

def public_job(job):  # Widok bez pełnych danych osobowych.
    return {k: v for k, v in job.items() if k != "input"}  # Formularz nie musi wracać w historii.

def validate_person(person):  # Minimalne dane podpisującego.
    if not isinstance(person, dict): raise ApiError("Nieprawidłowe dane osoby.")  # Odrzuć zły typ.
    clean = {k: str(person.get(k, "")).strip() for k in ("firstName", "lastName", "email", "address", "company")}  # Jawne pola.
    if any(len(v) > 250 for v in clean.values()): raise ApiError("Pole osoby może mieć maksymalnie 250 znaków.")  # Limit wejścia.
    if not clean["firstName"] or not clean["lastName"] or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", clean["email"]): raise ApiError("Podaj imię, nazwisko i poprawny e-mail każdej podpisującej osoby.")  # Walidacja serwerowa.
    return clean  # Bez danych przypadkowych.

def validate(data):  # Walidacja całego formularza.
    if not isinstance(data, dict): raise ApiError("Nieprawidłowy formularz.")  # Tylko JSON obiekt.
    clients = data.get("clients", [])  # Co najmniej jedna osoba.
    if not isinstance(clients, list) or not 1 <= len(clients) <= 10: raise ApiError("Dodaj od 1 do 10 klientów.")  # Ograniczony prototyp.
    result = {"clients": [validate_person(p) for p in clients], "developer": validate_person(data["developer"]) if data.get("developer") else None}  # Opcjonalny reprezentant.
    people = result["clients"] + ([result["developer"]] if result["developer"] else [])  # Wszyscy odbiorcy.
    if len({p["email"].casefold() for p in people}) != len(people): raise ApiError("Każdy podpisujący musi mieć inny adres e-mail w tym prototypie.")  # Nie scalaj osób po e-mailu.
    for key, limit in (("title", 160), ("property", 500), ("terms", 10000), ("signature", 30)):  # Limity tekstów.
        result[key] = str(data.get(key, "")).strip()  # Usunięcie skrajnych spacji.
        if len(result[key]) > limit: raise ApiError(f"Za długie pole: {key}.")  # Bez ogromnych PDF.
    if not result["title"]: raise ApiError("Podaj tytuł dokumentu.")  # Wymagany tytuł.
    if result["signature"] not in ("basic", "mobywatel", "qes", "qes_mobywatel"): raise ApiError("Nieznany rodzaj podpisu.")  # Zamknięty słownik.
    return result  # Uporządkowane dane.

def context(c):  # Przypisanie zleceń do środowiska i aplikacji.
    return c["environment"] + ":" + c.get("client_id", "")  # Nie zapisuj sekretów w zleceniu.

@admin.before_request  # Ochrona panelu przed obcymi originami i DNS rebinding.
def protect():  # Ngrok powinien wskazywać wyłącznie port 8001.
    if request.host not in ("127.0.0.1:8000", "localhost:8000"): abort(403)  # Jawne dozwolone hosty.
    if request.method in ("POST", "PUT", "DELETE"):  # Operacje zmieniające stan.
        if request.headers.get("Origin") not in (None, "http://127.0.0.1:8000", "http://localhost:8000"): abort(403)  # Blokada obcego originu.
        if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), CSRF): abort(403)  # Token dla lokalnego UI.

@admin.after_request  # Odpowiedzi panelu zawierają dane prywatne.
def headers(response):  # Zabezpieczenie przeglądarki.
    response.headers["Cache-Control"] = "no-store"  # Nie zapisuj odpowiedzi z danymi.
    response.headers["X-Content-Type-Options"] = "nosniff"  # Bez zgadywania MIME.
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"  # Brak skryptów z CDN.
    return response  # Kontynuacja odpowiedzi.

@admin.errorhandler(ApiError)  # Czytelne błędy biznesowe.
def api_error(error):  # Używane przez formularz.
    return jsonify(error=str(error)), 400  # Nigdy nie odsyłaj stack trace.

@admin.get("/")  # Główny panel.
def index():  # Renderowanie szablonu.
    return render_template("index.html", csrf=CSRF)  # Token tylko w lokalnej stronie.

@admin.get("/api/config")  # Konfiguracja bez wartości sekretów.
def read_config():  # UI dostaje tylko informację, które sekrety istnieją.
    c = config()  # Bieżąca konfiguracja.
    return jsonify({k: v for k, v in c.items() if k not in SECRET_FIELDS} | {"secrets_set": {k: bool(c.get(k)) for k in SECRET_FIELDS}})  # Maskowanie.

@admin.post("/api/config")  # Zapis z ekranu konfiguracji.
def write_config():  # Sprawdzenie pól przed zapisem.
    values = request.get_json()  # JSON z lokalnego panelu.
    if not isinstance(values, dict): raise ApiError("Konfiguracja musi być obiektem.")  # Poprawny typ.
    values = {k: v for k, v in values.items() if k in DEFAULT}  # Tylko znane pola.
    for key in SECRET_FIELDS:  # Puste pole nie usuwa zapisanego sekretu.
        if not values.get(key): values.pop(key, None)  # Zachowaj istniejący sekret.
    merged = config() | values  # Walidacja całego zestawu.
    if merged["mode"] not in ("demo", "live") or merged["environment"] not in BASES: raise ApiError("Nieprawidłowy tryb lub środowisko.")  # Lista dozwolona.
    if merged["auth_mode"] not in ("client_credentials", "bearer", "api_key", "refresh_token"): raise ApiError("Nieobsługiwany tryb autoryzacji.")  # Brak zgadywanych grantów.
    for key in ("qes_constraints", "mobywatel_constraints", "qes_mobywatel_constraints"):  # Profile muszą mieć format API.
        if not isinstance(merged[key], list) or not all(isinstance(x, dict) and isinstance(x.get("classifiers"), list) and isinstance(x.get("attributes"), dict) for x in merged[key]): raise ApiError("Profil " + key + " musi być tablicą obiektów constraints z classifiers i attributes.")  # Kontrola struktury.
    url = merged["webhook_url"]  # Publiczny URL odbiornika.
    if url and (urlsplit(url).scheme != "https" or urlsplit(url).path != "/webhooks/autenti" or urlsplit(url).query or urlsplit(url).fragment or urlsplit(url).username): raise ApiError("Webhook: https://TWOJA-DOMENA/webhooks/autenti, bez parametrów.")  # Prosty i bezpieczny adres.
    redirect_url = merged["oauth_redirect_url"]  # Osobny adres powrotu logowania.
    if redirect_url and (urlsplit(redirect_url).scheme != "https" or urlsplit(redirect_url).path != "/oauth/callback" or urlsplit(redirect_url).query or urlsplit(redirect_url).fragment or urlsplit(redirect_url).username): raise ApiError("OAuth redirect URL: https://TWOJA-DOMENA/oauth/callback.")  # Zgodny z publicznym serwerem.
    if any(k in values and values[k] != config().get(k) for k in ("client_id", "client_secret", "auth_mode", "environment", "refresh_token", "access_token")): values["access_token_expires_at"] = 0  # Zmiana danych unieważnia cache.
    if merged["environment"] != config()["environment"]: values["qes_issuance_enabled"] = False  # Aktywację trzeba potwierdzić dla nowego środowiska.
    save_config(values)  # Zapis dopiero po walidacji.
    return jsonify(message="Konfiguracja zapisana lokalnie.")  # Komunikat bez sekretów.

@admin.post("/api/check")  # Test autoryzacji bez wysyłania umów.
def check():  # Odczyt listy weryfikuje również read scope.
    c = config()  # Tryb i dane.
    if c["mode"] == "demo": return jsonify(message="Tryb DEMO: nie wykonano połączenia z Autenti.")  # Nie udawaj połączenia.
    with LOCK:  # Jednorazowy refresh token nie może być użyty równolegle.
        api = Autenti(config(), save_config)  # Adapter z aktualnym tokenem.
        api.decode(api.request("GET", "/document-processes"))  # Nie ujawniaj listy dokumentów konta.
    return jsonify(message="Autoryzacja i odczyt API działają. Nie potwierdza to uprawnień do wysyłki ani wydania QES.")  # Dokładny zakres testu.

@admin.post("/api/callback")  # Jawna rejestracja callbacka w Autenti.
def callback():  # Wywoływane tylko przyciskiem administratora.
    c = config()  # Konfiguracja usługi.
    if c["mode"] != "live" or not c["webhook_url"]: raise ApiError("Włącz LIVE i wpisz adres webhooka.")  # Bez rejestracji demonstracyjnej.
    with LOCK: return jsonify(message=Autenti(config(), save_config).register_callback(c["webhook_url"]))  # Jednorazowe tokeny chroni blokada.

@admin.post("/api/oauth/start")  # Użytkownik loguje się bezpośrednio na stronie Autenti.
def oauth_start():  # Nie zbieraj hasła do Autenti w CRM.
    c = config()  # Dane własnej aplikacji.
    if c["mode"] != "live" or not all(c.get(k) for k in ("client_id", "client_secret", "oauth_redirect_url")): raise ApiError("Włącz LIVE i zapisz client_id, client_secret oraz OAuth redirect URL.")  # Komplet ustawień.
    state = secrets.token_urlsafe(32)  # Nieprzewidywalny jednorazowy stan.
    with LOCK:  # Atomowa wymiana oczekujących logowań.
        PENDING_AUTH.clear(); PENDING_AUTH[state] = {"created": time.time(), "config": c}  # Jeden lokalny operator.
    params = {"client_id": c["client_id"], "redirect_uri": c["oauth_redirect_url"], "scope": c["scope"] or "full", "response_type": "code", "response_mode": "query", "state": state}  # Udokumentowany grant.
    return jsonify(url=BASES[c["environment"]] + "/auth/authorization?" + urlencode(params))  # Brak sekretu w URL.

@hook.get("/oauth/callback")  # Publiczny powrót OAuth, niezależny od webhooka podpisów.
def oauth_callback():  # State chroni wymianę kodu przed obcymi żądaniami.
    with LOCK:  # Jednorazowy kod i state.
        pending = PENDING_AUTH.pop(request.args.get("state", ""), None)  # Zużyj state raz.
        if not pending or time.time() - pending["created"] > 600: return "Nieprawidłowy lub wygasły state. Rozpocznij logowanie w lokalnym panelu.", 400  # Odmowa bez wywołania API.
        c = pending["config"]  # Te same parametry co na początku.
        if context(c) != context(config()) or c["client_secret"] != config()["client_secret"]: return "Konfiguracja zmieniła się podczas logowania. Rozpocznij ponownie.", 400  # Nie zapisz tokenu innego konta.
        if request.args.get("error") or not request.args.get("code"): return "Logowanie nie zostało zakończone. Wróć do lokalnego panelu.", 400  # Nie wyświetlaj surowej odpowiedzi.
        try:  # Wymiana kodu wyłącznie na backendzie.
            api = Autenti(c | {"auth_mode": "refresh_token"}, save_config)  # Zapis i rotacja tokenów.
            api.exchange({"client_id": c["client_id"], "client_secret": c["client_secret"], "grant_type": "authorization_code", "code": request.args["code"], "redirect_uri": c["oauth_redirect_url"]})  # Wartość redirect musi być identyczna.
        except ApiError: return "Autenti nie potwierdziło wymiany kodu i refresh tokenu. Sprawdź uprawnienia aplikacji i rozpocznij logowanie ponownie.", 400  # Bez sekretów.
    return "Połączono z Autenti. Zamknij tę kartę, wróć do panelu http://127.0.0.1:8000 i odśwież stronę. Tokeny zapisano lokalnie.", 200  # Bez tokenu w przeglądarce.

@hook.after_request  # Ochrona kodu OAuth w historii i referrerze.
def hook_headers(response):  # Nie zapisuj odpowiedzi z callbacka.
    response.headers["Cache-Control"] = "no-store"  # Brak cache.
    response.headers["Referrer-Policy"] = "no-referrer"  # Kod nie wycieka do kolejnych stron.
    response.headers["X-Content-Type-Options"] = "nosniff"  # Ścisły MIME.
    return response  # Gotowa odpowiedź.

@admin.post("/api/preview")  # PDF przed wysłaniem.
def preview():  # Nie kontaktuje się z Autenti.
    return send_file(BytesIO(make_pdf(validate(request.get_json()))), mimetype="application/pdf", download_name="umowa-testowa.pdf")  # Podgląd danych.

@admin.post("/api/jobs")  # Utwórz i wyślij dokument.
def create_job():  # Idempotencja lokalna na podstawie klucza z UI.
    raw = request.get_json()  # Formularz.
    data = validate(raw)  # Walidacja przed zewnętrznymi operacjami.
    key = str(raw.get("request_id", ""))  # Jedna intencja wysyłki ma jeden UUID.
    try: uuid.UUID(key)  # Nie akceptuj dowolnej ścieżki.
    except ValueError: raise ApiError("Brak poprawnego request_id.") from None  # Bez identyfikatora nie wysyłaj.
    with LOCK:  # Podwójny klik nie tworzy dwóch procesów.
        existing = next((j for j in all_jobs() if j["id"] == key), None)  # Sprawdź wcześniejszą próbę.
        if existing: return jsonify(public_job(existing))  # Nigdy nie ponawiaj niepewnego POST.
        c = config()  # Migawka konfiguracji zlecenia.
        if c["mode"] == "live" and data["signature"] in ("qes", "qes_mobywatel") and not c["qes_issuance_enabled"]: raise ApiError("Potwierdź w konfiguracji aktywację jednorazowego QES na koszt nadawcy przez Autenti.")  # Tego nie aktywują klucze.
        body = payload(data, c) if c["mode"] == "live" else None  # W LIVE brak profilu blokuje przed utworzeniem.
        pdf = make_pdf(data)  # Ostateczna wersja PDF.
        job = {"id": key, "title": data["title"], "input": data, "signature": data["signature"], "context": context(c), "mode": c["mode"], "status": "PREPARING", "process_id": None, "sha256": hashlib.sha256(pdf).hexdigest(), "error": "", "final": False, "created": time.time()}  # Historia procesu.
        (DATA / (key + "-source.pdf")).write_bytes(pdf)  # Zachowaj dokładnie wysłane bajty.
        save_job(job)  # Trwały zapis PRZED pierwszym POST.
        if c["mode"] == "demo":  # Bez zewnętrznej komunikacji.
            job["status"] = "DEMO_READY"  # Nie nazywaj symulacji podpisaniem.
            save_job(job)  # Zapis demonstracji.
            return jsonify(public_job(job))  # E-mail nie został wysłany.
        api = Autenti(c, save_config)  # Połączenie Autenti.
        try:  # Zachowaj każdy zakończony etap.
            job["status"] = "CREATING"; save_job(job)  # POST może zakończyć się niepewnie.
            job["process_id"] = api.create(body)  # Identyfikator od dostawcy.
            job["status"] = "DRAFT"; save_job(job)  # Zapis przed uploadem.
            api.upload(job["process_id"], pdf)  # Właściwy PDF.
            job["status"] = "UPLOADED"; save_job(job)  # Potwierdzony upload.
            api.send(job["process_id"])  # Autenti wysyła zaproszenia do wszystkich SIGNER.
            job["status"] = "SENT"  # Potwierdzona akcja, nie dowód dostarczenia e-maila.
        except ApiError as error: job["error"] = str(error); job["status"] = "NEEDS_REVIEW"  # Ręczna ocena przed powtórką.
        save_job(job)  # Zachowaj również stan błędu.
        return jsonify(public_job(job))  # Użytkownik widzi wynik.

def sync_job(job):  # Pobierz stan i ewentualnie finalny plik.
    c = config()  # Aktualne tokeny, to samo środowisko.
    if job["mode"] != "live" or not job["process_id"]: return job  # Brak zewnętrznego procesu.
    if context(c) != job["context"] or c["mode"] != "live": raise ApiError("Przywróć środowisko i client_id użyte do utworzenia tego procesu.")  # Nie mieszaj organizacji.
    api = Autenti(c, save_config)  # Właściwa autoryzacja.
    details = api.details(job["process_id"])  # Źródło prawdy zamiast redirecta.
    if not isinstance(details, dict) or not details.get("status"): raise ApiError("Brak statusu procesu w odpowiedzi.")  # Nie nadpisuj stanu przypadkowo.
    job["status"] = details["status"]  # Oryginalny status Autenti.
    job["participants"] = [{"role": p.get("role"), "status": p.get("participationStatus")} for p in details.get("parties", [])]  # Bez publikowania linków podpisu.
    job["error"] = ""  # Udany odczyt usuwa stary błąd.
    if job["status"] == "COMPLETED" and not job["final"]:  # Tylko podpisy wszystkich stron.
        content = api.final_pdf(job["process_id"])  # Wybierz SIGNED_CONTENT_FILE.
        if content:  # Plik może pojawić się z opóźnieniem.
            destination = DATA / (job["id"] + "-signed.pdf")  # Bez obcych nazw plików.
            temporary = destination.with_suffix(".tmp")  # Atomowy zapis dokumentu.
            temporary.write_bytes(content); temporary.replace(destination)  # Brak częściowego PDF.
            job["final"] = True  # Potwierdzony lokalny plik.
            job["signed_sha256"] = hashlib.sha256(content).hexdigest()  # Kontrola integralności zapisu.
    save_job(job)  # Trwały wynik synchronizacji.
    return job  # Dane do panelu lub workera.

@admin.get("/api/jobs")  # Historia bez wywołań do Autenti.
def jobs():  # Frontend odświeża ten endpoint.
    return jsonify([public_job(j) for j in all_jobs()])  # Tylko metadane.

@admin.post("/api/jobs/<identifier>/sync")  # Ręczna synchronizacja po webhooku lub problemie.
def sync(identifier):  # Bez ponownej wysyłki dokumentu.
    with LOCK: return jsonify(public_job(sync_job(get_job(identifier))))  # Serializacja zmian.

@admin.get("/api/jobs/<identifier>/<kind>.pdf")  # Lokalny dokument.
def download(identifier, kind):  # Żadnych dowolnych ścieżek od użytkownika.
    job = get_job(identifier)  # Musi istnieć w bazie.
    if kind not in ("source", "signed") or (kind == "signed" and not job["final"]): abort(404)  # Finalny dopiero po pobraniu.
    return send_file(DATA / (job["id"] + "-" + kind + ".pdf"), mimetype="application/pdf", as_attachment=True, download_name="umowa-" + kind + ".pdf")  # Zachowaj oryginał.

def verify_jws(raw, signature, environment):  # Detached JWS, bez deserializacji body przed weryfikacją.
    try:  # Nie ufaj kid/alg/url z wejścia.
        parts = signature.split(".")  # header..signature.
        if len(parts) != 3 or parts[1]: return False  # Wyłącznie format detached z dokumentacji.
        header = jwt.get_unverified_header(signature)  # Tylko wybór zaufanego klucza.
        if header.get("alg") != "RS256" or header.get("crit") or header.get("b64") is False: return False  # Ograniczony wspierany algorytm.
        response = requests.get(JWKS[environment], timeout=(5, 15), allow_redirects=False)  # Stały adres JWKS.
        response.raise_for_status()  # Nie akceptuj błędów infrastruktury.
        key = next(k for k in response.json()["keys"] if k.get("kid") == header.get("kid") and k.get("kty") == "RSA")  # Klucz od Autenti.
        public = jwt.PyJWK.from_dict(key).key  # Zdekoduj RSA.
        full = parts[0] + "." + base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + parts[2]  # Oryginalne bajty payload.
        jwt.api_jws.decode_complete(full, public, algorithms=["RS256"])  # Podpis JWS również dla tablicy JSON.
        return True  # Dopiero teraz można czytać zdarzenia.
    except (ValueError, KeyError, StopIteration, jwt.PyJWTError): return False  # Niepoprawny podpis.

@hook.post("/webhooks/autenti")  # Jedyna publiczna operacja POST.
def incoming():  # Zapis do trwałej kolejki przed ACK.
    c = config()  # Klucze właściwego środowiska.
    if c["mode"] != "live": return jsonify(error="Webhook disabled in demo"), 409  # Nie mieszaj demo i LIVE.
    raw = request.get_data(cache=False)  # Bajty niezmienione przez parser.
    try: valid = verify_jws(raw, request.headers.get("x-jws-signature", ""), c["environment"])  # Kryptograficzne uwierzytelnienie.
    except requests.RequestException: return jsonify(error="JWKS unavailable"), 503  # Autenti ponowi przy awarii.
    if not valid: return jsonify(error="Invalid signature"), 401  # Nie przyjmuj podszytych webhooków.
    try: events = json.loads(raw)  # Parsowanie dopiero po weryfikacji.
    except ValueError: return jsonify(error="Invalid JSON"), 400  # Niepoprawny payload.
    if not isinstance(events, list) or not all(isinstance(e, dict) and isinstance(e.get("id"), str) for e in events): return jsonify(error="Expected events array"), 400  # Walidacja całej paczki.
    with db() as connection:  # Jedna transakcja i idempotencja.
        for event in events:  # Zdarzenia całej organizacji, filtrowane przez worker.
            connection.execute("INSERT OR IGNORE INTO events (id,body) VALUES (?,?)", (c["environment"] + ":" + event["id"], json.dumps({"environment": c["environment"], "event": event})))  # Ponowienie nie duplikuje pracy.
    return jsonify(received=True), 200  # ACK po zatwierdzeniu transakcji.

@hook.get("/health")  # Minimalna kontrola tunelu.
def health():  # Bez konfiguracji, danych lub sekretów.
    return jsonify(service="autenti-webhook", ok=True)  # Publiczny status.

def worker():  # Trwałe przetwarzanie webhooków także po restarcie.
    while True:  # Jeden worker prototypu.
        try:  # Błąd zdarzenia nie zabija odbiornika.
            with db() as connection: rows = connection.execute("SELECT id,body,attempts FROM events WHERE done=0 AND next_try<=? LIMIT 20", (time.time(),)).fetchall()  # Gotowe zadania.
            for identifier, body, attempts in rows:  # Każde zdarzenie osobno.
                try:  # Wyszukaj proces i synchronizuj przez API.
                    record = json.loads(body); event = record["event"]  # Envelope z przypisanym środowiskiem.
                    pid = event.get("object", {}).get("id")  # Udokumentowany obiekt procesu.
                    with LOCK:  # Nie ścigaj się z formularzem i odświeżaniem.
                        job = next((j for j in all_jobs() if j["process_id"] == pid and j["context"].startswith(record["environment"] + ":")), None)  # Ignoruj obce dokumenty organizacji.
                        if job:  # Zlecenie pochodzi z tego prototypu.
                            updated = sync_job(job)  # Pobierz stan od dostawcy.
                            if event.get("eventType") == "EVENT_CLASSIFIER-UNIQUE_TYPE:DOCUMENT_PROCESS_COMPLETED" and updated["status"] != "COMPLETED": raise ApiError("Oczekiwanie na spójny status finalizacji.")  # Event może wyprzedzać replikę odczytu.
                            if updated["status"] == "COMPLETED" and not updated["final"]: raise ApiError("Oczekiwanie na finalny PDF.")  # Ponów pobranie przy opóźnieniu.
                    with db() as connection: connection.execute("UPDATE events SET done=1 WHERE id=?", (identifier,))  # Sukces lub nieznany proces.
                except Exception:  # Nie loguj treści zdarzeń ani sekretów.
                    with db() as connection: connection.execute("UPDATE events SET attempts=attempts+1,next_try=? WHERE id=?", (time.time() + min(3600, 30 * 2 ** min(attempts, 7)), identifier))  # Backoff i trwałe ponowienie.
        except Exception: pass  # Chwilowo niedostępna baza; następny przebieg spróbuje ponownie.
        time.sleep(5)  # Krótkie odstępy pomiędzy zadaniami.

class PrivateRequestHandler(WSGIRequestHandler):  # Nie zapisuj kodów OAuth w logach HTTP.
    def log_request(self, code="-", size="-"): pass  # Panel pokazuje statusy bez logowania query string.

if __name__ == "__main__":  # Uruchomienie lokalne bez debuggera.
    os.umask(0o077)  # Nowe pliki prywatne.
    init()  # Baza i katalog danych.
    threading.Thread(target=worker, daemon=True).start()  # Odbiór dokumentów w tle.
    server = make_server("127.0.0.1", 8001, hook, threaded=True, request_handler=PrivateRequestHandler)  # Publiczny tunel trafia tutaj.
    threading.Thread(target=server.serve_forever, daemon=True).start()  # Osobny serwer webhooka.
    print("CRM: http://127.0.0.1:8000 | ngrok http 8001 | Ctrl+C kończy aplikację")  # Bez sekretów w terminalu.
    make_server("127.0.0.1", 8000, admin, threaded=True, request_handler=PrivateRequestHandler).serve_forever()  # Panel tylko lokalny.
