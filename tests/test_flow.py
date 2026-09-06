"""Testy kontraktu HTTP z atrapą Autenti; nie wysyłają e-maili."""
import base64  # Budowa detached JWS.
import json  # Dane testowe.
import uuid  # Klucze idempotencji.
import pytest  # Izolowane scenariusze.
import jwt  # Podpis testowego webhooka.
from cryptography.hazmat.primitives.asymmetric import rsa  # Rzeczywisty test kryptograficzny.
import app  # Backend i endpointy.
import autenti  # Adapter API.

def data(developer=False):  # Nieszkodliwe przykładowe adresy.
    result = {"request_id": str(uuid.uuid4()), "title": "Test rezerwacji", "property": "Łódź, lokal 12", "terms": "Zażółć gęślą jaźń", "signature": "basic", "clients": [{"firstName": "Anna", "lastName": "Żółkiewska", "email": "anna@example.com"}]}  # Polski tekst.
    if developer: result["developer"] = {"firstName": "Jan", "lastName": "Nowak", "email": "jan@example.com", "company": "Test"}  # Druga osoba.
    return result  # Dane do wywołań.

@pytest.fixture  # Osobny katalog w każdym teście.
def client(tmp_path, monkeypatch):  # Żadnych prawdziwych sekretów.
    monkeypatch.setattr(app, "DATA", tmp_path / "data")  # Izolowana baza.
    monkeypatch.setattr(app, "CONFIG", tmp_path / "config.json")  # Izolowana konfiguracja.
    app.init()  # Utwórz tabele.
    return app.admin.test_client()  # Bez uruchamiania serwera sieciowego.

def post(client, path, body):  # Autoryzowane wywołanie lokalnego UI.
    return client.post(path, json=body, headers={"X-CSRF-Token": app.CSRF}, base_url="http://127.0.0.1:8000")  # Właściwy Host.

class Response:  # Minimalna odpowiedź requests.
    def __init__(self, value, status=200, content=None):  # JSON lub PDF.
        self.value, self.status_code, self.headers = value, status, {}  # Pola protokołu.
        self.content = content if content is not None else json.dumps(value).encode()  # Bajty.
        self.text = self.content.decode(errors="replace")  # Tekst odpowiedzi.
    def json(self): return json.loads(self.content)  # Realne parsowanie również wywołuje błąd dla PDF.
    def raise_for_status(self): return None  # Poprawny JWKS w teście.

def test_demo_optional_developer_and_secrets(client):  # Demo nie wymaga drugiej strony ani kluczy.
    result = post(client, "/api/jobs", data()).get_json()  # Generuj demonstrację.
    assert result["status"] == "DEMO_READY" and result["process_id"] is None  # Nie udawaj podpisania.
    assert post(client, "/api/preview", data(True)).data.startswith(b"%PDF-")  # PDF z dwiema stronami umowy.
    post(client, "/api/config", {"client_secret": "SECRET"})  # Zapisz testowy sekret.
    public = client.get("/api/config", base_url="http://127.0.0.1:8000").get_json()  # Odczyt konfiguracji.
    assert "client_secret" not in public and public["secrets_set"]["client_secret"]  # Sekret nie wraca.

def test_csrf_host_and_public_surface(client):  # Tunel nie udostępnia panelu.
    assert client.get("/", base_url="http://evil.test:8000").status_code == 403  # DNS rebinding.
    assert client.post("/api/config", json={}, base_url="http://127.0.0.1:8000").status_code == 403  # CSRF.
    assert app.hook.test_client().get("/api/config").status_code == 404  # Oddzielny publiczny serwer.

def test_live_roundtrip_and_duplicate(client, monkeypatch):  # Pełny kontrakt adaptera z atrapą Autenti.
    post(client, "/api/config", {"mode": "live", "auth_mode": "bearer", "access_token": "TEST", "client_id": "test-app"})  # Nie używa sieci.
    calls = []  # Rejestr metod i schematów.
    final = b"%PDF-1.7\nSIGNED-TEST-BYTES"  # Jednoznaczne bajty finalnego pliku.
    def fake(method, url, **kwargs):  # Sprawdź żądania na granicy HTTP.
        calls.append((method, url, kwargs))  # Zachowaj do asercji.
        if method == "POST" and url.endswith("/document-processes"):  # Utworzenie procesu.
            assert len(kwargs["json"]["parties"]) == 2  # Klient i przedstawiciel są SIGNER.
            return Response({"id": "DOCUMENT_PROCESS:test"})  # Identyfikator od API.
        if method == "POST" and url.endswith("/files"):  # Multipart upload.
            assert kwargs["files"]["file"][1].startswith(b"%PDF-")  # Prawdziwy PDF.
            assert kwargs["files"]["fileMeta"][2] == "application/json"  # Format metadanych.
            return Response({"id": "FILE-SOURCE_FILE:test"})  # Potwierdzenie uploadu.
        if method == "POST" and url.endswith("/actions"):  # Wysyłka e-mail.
            assertion = json.loads(base64.b64decode(kwargs["headers"]["X-ASSERTION"]))  # Zweryfikuj akcję.
            assert assertion["attributes"]["selectedIds"] == ["EVENT_CLASSIFIER-UNIQUE_TYPE:DOCUMENT_SENT"]  # Właściwa operacja.
            return Response([{"eventType": "EVENT_CLASSIFIER-UNIQUE_TYPE:DOCUMENT_SENT"}])  # Potwierdzona wysyłka.
        if url.endswith("/content"): return Response(None, content=final)  # Bajty bez zmian.
        if url.endswith("/files"): return Response([{"id": "FILE-SIGNED_CONTENT_FILE:test/DTBS", "filePurpose": "SIGNED_CONTENT_FILE"}])  # Ukośnik w identyfikatorze.
        return Response({"status": "COMPLETED", "parties": []})  # Wszyscy podpisali.
    monkeypatch.setattr(autenti.requests, "request", fake)  # Żadnego prawdziwego API.
    form = data(True)  # Dwie osoby.
    result = post(client, "/api/jobs", form).get_json()  # Create → upload → send.
    assert result["status"] == "SENT"  # Potwierdzenie z eventu.
    post(client, "/api/jobs", form)  # Ten sam request_id.
    assert len(calls) == 3  # Brak dodatkowej wysyłki.
    synced = post(client, f"/api/jobs/{form['request_id']}/sync", {}).get_json()  # Odbierz stan i plik.
    assert synced["final"] and synced["status"] == "COMPLETED"  # Sukces po wszystkich podpisach.
    assert (app.DATA / (form["request_id"] + "-signed.pdf")).read_bytes() == final  # Nie modyfikuj podpisanego dokumentu.
    assert any("%2FDTBS/content" in call[1] for call in calls)  # ID kodowane zgodnie z dokumentacją.

def test_qes_and_mobywatel_fail_closed(client):  # Nie obniżaj rodzaju podpisu.
    post(client, "/api/config", {"mode": "live"})  # Rzeczywisty tryb bez uprawnień.
    form = data(); form["signature"] = "qes"  # Brak aktywacji jednorazowej usługi.
    assert post(client, "/api/jobs", form).status_code == 400  # Blokada przed API.
    form["signature"] = "mobywatel"  # Brak profilu dostawcy.
    assert post(client, "/api/jobs", form).status_code == 400  # Bez zastąpienia przez BASIC.
    assert app.all_jobs() == []  # Brak utworzonych zleceń.

def test_webhook_signature_tamper_and_replay(client, monkeypatch):  # Prawdziwy RSA/JWS i trwała idempotencja.
    post(client, "/api/config", {"mode": "live"})  # Odbiornik aktywny.
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)  # Testowy klucz.
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key())); jwk["kid"] = "test-key"  # Publiczny zestaw.
    monkeypatch.setattr(app.requests, "get", lambda *a, **k: Response({"keys": [jwk]}))  # Zastąp zaufany endpoint JWKS.
    raw = json.dumps([{"id": "event-test", "object": {"id": "DOCUMENT_PROCESS:unknown"}}]).encode()  # Paczka Autenti.
    signed = jwt.api_jws.encode(raw, private, algorithm="RS256", headers={"kid": "test-key"})  # Podpisz dokładne bajty.
    parts = signed.split("."); detached = parts[0] + ".." + parts[2]  # Format nagłówka Autenti.
    public = app.hook.test_client()  # Publiczny endpoint.
    for _ in range(2): assert public.post("/webhooks/autenti", data=raw, headers={"x-jws-signature": detached}).status_code == 200  # Ponowienie ACK.
    with app.db() as connection: assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1  # Jedno zdarzenie.
    assert public.post("/webhooks/autenti", data=raw + b" ", headers={"x-jws-signature": detached}).status_code == 401  # Nawet zmiana spacji unieważnia podpis.
    assert public.post("/webhooks/autenti", data=raw).status_code == 401  # Bez podpisu odmowa.

def test_unknown_send_result_not_success(client, monkeypatch):  # Nie uznawaj challenge za wysłaną umowę.
    api = autenti.Autenti(app.DEFAULT | {"auth_mode": "bearer", "access_token": "test"})  # Testowy adapter.
    monkeypatch.setattr(autenti.requests, "request", lambda *a, **k: Response([{"challenges": [{"type": "CONSENT"}]}]))  # Dodatkowa interakcja.
    with pytest.raises(autenti.ApiError): api.send("DOCUMENT_PROCESS:test")  # Stan wymaga dostosowania.

def test_oauth_state_one_time_and_rotation(client, monkeypatch):  # Callback OAuth jest związany z rozpoczętym logowaniem.
    post(client, "/api/config", {"mode": "live", "client_id": "test-app", "client_secret": "test-secret", "oauth_redirect_url": "https://test.ngrok-free.app/oauth/callback"})  # Konfiguracja testowa.
    started = post(client, "/api/oauth/start", {}).get_json()  # Wygeneruj state.
    from urllib.parse import parse_qs, urlsplit  # Parametry adresu logowania.
    state = parse_qs(urlsplit(started["url"]).query)["state"][0]  # Jednorazowy stan.
    calls = []  # Kontrola liczby wymian.
    def exchange(url, **kwargs):  # Atrapa token endpoint.
        calls.append(kwargs["json"])  # Żądanie nie może trafić na frontend.
        return Response({"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 1800})  # Para tokenów.
    monkeypatch.setattr(autenti.requests, "post", exchange)  # Bez faktycznej autoryzacji.
    public = app.hook.test_client()  # Callback w publicznej części.
    assert public.get("/oauth/callback?state=invalid&code=abc").status_code == 400  # Obcy callback odrzucony.
    response = public.get("/oauth/callback", query_string={"state": state, "code": "test-code"})  # Właściwy callback.
    assert response.status_code == 200 and b"access-1" not in response.data  # Sekret nie wraca.
    assert app.config()["auth_mode"] == "refresh_token" and app.config()["refresh_token"] == "refresh-1"  # Zapis tokenów.
    assert public.get("/oauth/callback", query_string={"state": state, "code": "test-code"}).status_code == 400  # State zużyty.
    assert len(calls) == 1 and calls[0]["grant_type"] == "authorization_code"  # Jedna wymiana kodu.
    api = autenti.Autenti(app.config(), app.save_config)  # Kolejna instancja korzysta z cache.
    assert api.authorization() == "Bearer access-1" and len(calls) == 1  # Brak niepotrzebnego użycia refresh tokenu.

def test_two_clients_payload_and_qes():  # Każdy klient i reprezentant ma własne wymaganie QES.
    form = data(True); form["signature"] = "qes"  # Kwalifikowane podpisy.
    form["clients"].append({"firstName": "Adam", "lastName": "Nowak", "email": "adam@example.com"})  # Współrezerwujący.
    body = autenti.payload(app.validate(form), app.DEFAULT)  # Zbuduj żądanie.
    assert len(body["parties"]) == 3  # Dwie osoby i przedstawiciel.
    assert all(p["constraints"][0]["attributes"]["requiredClassifiers"] == ["SIGNATURE_PROVIDER-SIGNATURE_TYPE:QUALIFIED"] for p in body["parties"])  # Brak osłabienia podpisu.
