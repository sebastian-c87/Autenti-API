"""Adapter publicznego API V2; bez zgadywania identyfikatorów dostawców."""
import base64  # Kodowanie asercji wymaganej przez API.
import json  # Serializacja żądań.
import time  # Czas ważności tokenu.
from urllib.parse import quote  # Bezpieczne identyfikatory w ścieżkach.
import requests  # Klient HTTPS z weryfikacją certyfikatów.

BASES = {"accept": "https://api.accept.autenti.net/api/v2", "production": "https://api.autenti.com/api/v2"}  # Oficjalne adresy.
JWKS = {"accept": "https://autenti.com/developers/keys/accept-webhook.jwks", "production": "https://autenti.com/developers/keys/webhook.jwks"}  # Zaufane klucze webhooków.

class ApiError(Exception):  # Kontrolowany błąd bez ujawniania sekretów.
    pass  # Treść ustala wywołujący adapter.

def constraint(level):  # Wymagany poziom podpisu uczestnika.
    return {"constrainedActions": ["ACTION:SIGNATURE_APPLICATION"], "classifiers": ["CONSTRAINT-UNIQUE_TYPE:SIGNATURE_TYPE"], "attributes": {"requiredClassifiers": ["SIGNATURE_PROVIDER-SIGNATURE_TYPE:" + level]}}  # Schemat Autenti.

def signature_constraints(method, config):  # Nie zastępuj niedostępnej metody słabszym podpisem.
    if method == "basic":  # Zwykły podpis Autenti.
        return [constraint("BASIC")]  # Jawne wymaganie BASIC.
    if method == "qes":  # Podpis kwalifikowany.
        return [constraint("QUALIFIED")] + config.get("qes_constraints", [])  # Opcjonalne ograniczenia dostawcy.
    key = {"mobywatel": "mobywatel_constraints", "qes_mobywatel": "qes_mobywatel_constraints"}.get(method)  # Profile indywidualne.
    if not key or not config.get(key):  # Brak potwierdzonej konfiguracji to blokada.
        raise ApiError("Ta metoda wymaga profilu constraints od Autenti. Nie wysłano dokumentu.")  # Bez fikcyjnego wsparcia.
    return ([constraint("QUALIFIED")] if method == "qes_mobywatel" else []) + config[key]  # mObywatel to metoda identyfikacji.

def payload(data, config):  # Zamiana formularza na proces Autenti.
    people = data["clients"] + ([data["developer"]] if data.get("developer") else [])  # Deweloper jest opcjonalny w teście.
    parties = []  # Lista osób faktycznie podpisujących.
    for person in people:  # Każda osoba otrzymuje oddzielne zaproszenie.
        rules = signature_constraints(data["signature"], config)  # Ta sama wybrana metoda dla stron.
        parties.append({"party": {"firstName": person["firstName"], "lastName": person["lastName"], "contacts": [{"type": "CONTACT-TYPE:EMAIL", "attributes": {"email": person["email"]}}]}, "role": "SIGNER", "constraints": rules})  # Udokumentowany uczestnik.
    if config.get("sender_organization"):  # Tylko przy aktywnej funkcji nadawcy organizacyjnego.
        parties.append({"party": {"id": "PARTY-TENANT:SELF"}, "role": "SENDER"})  # Organizacja nie jest podpisującym.
    return {"title": data["title"], "description": "Dokument testowy z prototypu CRM. Prosimy zapoznać się z PDF.", "processLanguage": "pl", "parties": parties}  # Domyślne e-maile obsługuje Autenti.

class Autenti:  # Stan tokenu istnieje tylko na serwerze.
    def __init__(self, config, save_tokens=None):  # Konfiguracja konkretnego środowiska.
        self.config, self.save_tokens = config, save_tokens  # Odświeżone tokeny można zachować lokalnie.
        self.base = BASES[config["environment"]]  # Nie wysyłaj sekretów pod dowolny URL.
        self.token, self.expires = "", 0  # Cache krótkotrwałego tokenu.

    def exchange(self, body):  # Pobranie tokenu OAuth2.
        try:  # Błędy sieciowe nie powinny wyświetlać żądania.
            response = requests.post(self.base + "/auth/token", json=body, timeout=(10, 40), allow_redirects=False)  # JSON według Autenti.
        except requests.RequestException:  # Nie wypisuj wyjątków z danymi uwierzytelniającymi.
            raise ApiError("Nie udało się połączyć z serwerem autoryzacji Autenti.") from None  # Czytelny komunikat.
        result = self.decode(response)  # Sprawdź również wyzwania autoryzacji.
        if not isinstance(result, dict) or not result.get("access_token"):  # Sam HTTP 200 nie wystarcza.
            raise ApiError("Autenti nie zwróciło access_token. Sprawdź grant, scope i dodatkowe wymagania autoryzacji.")  # Brak udawanej autoryzacji.
        self.token = result["access_token"]  # Token bieżącego klienta.
        self.expires = time.time() + max(0, int(result.get("expires_in", 300)) - 30)  # Zapas na czas żądania.
        if self.config["auth_mode"] == "refresh_token" and self.save_tokens:  # Obsługa rotacji refresh tokenu.
            if not result.get("refresh_token"): raise ApiError("Autenti nie zwróciło nowego refresh_token. Wymagane ponowne logowanie.")  # Nie używaj ponownie zużytego tokenu.
            tokens = {"access_token": self.token, "refresh_token": result["refresh_token"], "access_token_expires_at": self.expires, "auth_mode": "refresh_token"}  # Rotacja jednorazowego tokenu.
            self.config.update(tokens); self.save_tokens(tokens)  # Atomowy zapis i aktualizacja instancji.
        return self.token  # Zwróć token wewnętrznie.

    def authorization(self):  # Wybór jednego sposobu uwierzytelnienia.
        mode = self.config["auth_mode"]  # Nie łącz niezależnych grantów.
        if mode == "api_key":  # Klucz API przyznany przez Autenti.
            if not self.config.get("api_key"): raise ApiError("Uzupełnij API key.")  # Sprawdź brak klucza.
            return "api-key " + self.config["api_key"]  # Właściwy schemat nagłówka.
        if mode == "bearer":  # Token uzyskany poza prototypem, np. oficjalnym Postmanem.
            if not self.config.get("access_token"): raise ApiError("Uzupełnij access_token.")  # Token musi istnieć.
            return "Bearer " + self.config["access_token"]  # Bez ekspozycji w UI.
        if self.token and time.time() < self.expires: return "Bearer " + self.token  # Wykorzystaj ważny token.
        if mode == "refresh_token" and self.config.get("access_token") and time.time() < float(self.config.get("access_token_expires_at", 0)): return "Bearer " + self.config["access_token"]  # Nie obracaj refresh tokenu przy każdym statusie.
        if not self.config.get("client_id") or not self.config.get("client_secret"): raise ApiError("Uzupełnij client_id i client_secret.")  # Minimalne dane.
        body = {"client_id": self.config["client_id"], "client_secret": self.config["client_secret"], "grant_type": mode}  # Żądanie tokenu.
        if mode == "refresh_token": body["refresh_token"] = self.config.get("refresh_token", "")  # Wymiana tokenu odnawialnego.
        if self.config.get("scope"): body["scope"] = self.config["scope"]  # Tylko zakres uzgodniony z Autenti.
        return "Bearer " + self.exchange(body)  # Token do API.

    def decode(self, response):  # Walidacja odpowiedzi bez logowania danych osobowych.
        if not 200 <= response.status_code < 300:  # Obsłuż błędy i przekierowania.
            hints = {401: "Token nieważny lub wygasł.", 403: "Brak uprawnień do operacji.", 402: "Brak pakietu lub limitu usługi.", 429: "Limit żądań. Odczekaj Retry-After: " + response.headers.get("Retry-After", "według Autenti")}  # Diagnostyka.
            raise ApiError(f"Autenti HTTP {response.status_code}. " + hints.get(response.status_code, "Sprawdź konfigurację procesu i dane. Przy niepewnym wyniku nie ponawiaj wysyłki automatycznie."))  # Bez treści zawierającej sekrety.
        try: return response.json()  # JSON może być obiektem lub tablicą.
        except ValueError: raise ApiError("Nieoczekiwana odpowiedź Autenti zamiast JSON.") from None  # Nie uznawaj HTML za sukces.

    def request(self, method, path, **kwargs):  # Wszystkie wywołania mają limit czasu i stały host.
        overrides = kwargs.pop("headers", {})  # Opcjonalna autoryzacja administratora.
        headers = {"Authorization": overrides.get("Authorization") or self.authorization(), "Accept": "application/json"}  # Nie pobieraj zbędnego tokenu przy management_token.
        headers.update(overrides)  # Asercje i autoryzacja administratora.
        try: response = requests.request(method, self.base + path, headers=headers, timeout=(10, 60), allow_redirects=False, **kwargs)  # Bez automatycznego ponawiania POST.
        except requests.RequestException: raise ApiError("Błąd połączenia. Wynik operacji może być nieznany; sprawdź proces w Autenti przed ponowieniem.") from None  # Istotne dla kosztów.
        return response  # Wywołujący wybiera JSON lub plik.

    def create(self, body):  # Utworzenie wersji roboczej, jeszcze bez wysyłki.
        result = self.decode(self.request("POST", "/document-processes", json=body))  # Standard V2.
        if not isinstance(result, dict) or not str(result.get("id", "")).startswith("DOCUMENT_PROCESS:"): raise ApiError("Brak identyfikatora procesu. Sprawdź Autenti przed ponowieniem.")  # Nie zgaduj ID.
        return result["id"]  # Zachowaj identyfikator od razu po utworzeniu.

    def upload(self, pid, content):  # Wysyłka PDF jako multipart.
        meta = {"filename": "umowa-testowa.pdf", "filePurpose": "SOURCE_FILE", "mimeType": "application/pdf"}  # Opis źródła.
        parts = {"fileMeta": (None, json.dumps(meta), "application/json"), "file": ("umowa-testowa.pdf", content, "application/pdf")}  # Dwie części według dokumentacji.
        result = self.decode(self.request("POST", f"/document-processes/{quote(pid, safe='')}/files", files=parts))  # Boundary ustala requests.
        if not isinstance(result, dict) or not result.get("id"): raise ApiError("Autenti nie potwierdziło dodania pliku.")  # Nie wysyłaj pustego procesu.
        return result  # Dane pliku.

    def send(self, pid):  # Uruchomienie domyślnej wysyłki e-mail przez Autenti.
        assertion = {"classifiers": ["CHALLENGE_CLASSIFIER-UNIQUE_TYPE:ACTION_SELECTION"], "attributes": {"selectedIds": ["EVENT_CLASSIFIER-UNIQUE_TYPE:DOCUMENT_SENT"]}}  # Udokumentowana akcja.
        encoded = base64.b64encode(json.dumps(assertion).encode()).decode()  # Wartość X-ASSERTION.
        result = self.decode(self.request("POST", f"/document-processes/{quote(pid, safe='')}/actions", headers={"X-ASSERTION": encoded}))  # Wyślij tylko raz.
        events = result if isinstance(result, list) else [result]  # Ujednolicenie odpowiedzi.
        if not any(isinstance(e, dict) and e.get("eventType") == "EVENT_CLASSIFIER-UNIQUE_TYPE:DOCUMENT_SENT" for e in events): raise ApiError("Wysyłka nie została potwierdzona zdarzeniem DOCUMENT_SENT. Możliwe dodatkowe challenges; kontynuuj w Autenti lub dostosuj adapter.")  # Brak fałszywego sukcesu.

    def details(self, pid):  # Bieżący stan procesu.
        return self.decode(self.request("GET", f"/document-processes/{quote(pid, safe='')}"))  # Tylko zapisany proces.

    def final_pdf(self, pid):  # Pobieranie wyłącznie finalnego, podpisanego dokumentu.
        path = f"/document-processes/{quote(pid, safe='')}/files"  # Kolekcja plików procesu.
        response = self.request("GET", path, headers={"Accept": "application/stream+json"})  # Streaming omija paginację.
        if not 200 <= response.status_code < 300: self.decode(response)  # Wspólne błędy.
        try:  # Serwer może zwrócić tablicę JSON lub NDJSON.
            listed = response.json()  # Obsługa zwykłego JSON.
            listed = listed if isinstance(listed, list) else [listed]  # Jeden plik też jest kolekcją.
        except ValueError: listed = [json.loads(line) for line in response.text.splitlines() if line.strip()]  # Strumień JSON.
        final = next((f for f in listed if f.get("filePurpose") == "SIGNED_CONTENT_FILE"), None)  # Nigdy PARTIALLY_SIGNED.
        if not final: return None  # Finalizacja może jeszcze trwać.
        result = self.request("GET", path + "/" + quote(final["id"], safe="") + "/content", headers={"Accept": "application/pdf"})  # Koduj także ukośnik ID.
        if not 200 <= result.status_code < 300: self.decode(result)  # Sprawdź HTTP.
        if not result.content.startswith(b"%PDF-"): raise ApiError("Plik wynikowy nie jest PDF; nie zapisano go jako podpisanej umowy.")  # Kontrola formatu.
        return result.content  # Oryginalne bajty bez modyfikacji.

    def register_callback(self, url):  # Rejestracja przez administratora.
        headers = {}  # Domyślnie bieżąca autoryzacja.
        if self.config.get("management_token"): headers["Authorization"] = "Bearer " + self.config["management_token"]  # Osobny token notification_management.
        current = self.decode(self.request("GET", "/applications/callbacks", headers=headers))  # Nie mnożymy tych samych callbacków.
        if isinstance(current, list) and any(c.get("callbackParameters", {}).get("callbackUrl") == url for c in current): return "Webhook jest już zarejestrowany."  # Idempotencja rejestracji.
        self.decode(self.request("POST", "/applications/callbacks", headers=headers, json={"callbackAdapterId": "CALLBACK_ADAPTER:API_V2", "callbackParameters": {"callbackUrl": url}}))  # Oficjalny endpoint.
        return "Webhook zarejestrowany w Autenti."  # Potwierdzenie.
