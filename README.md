# Autenti CRM Prototype – instrukcja macOS i Windows

Lokalna aplikacja do sprawdzenia przepływu: dane stron → PDF → zaproszenia e-mail wysyłane przez Autenti → podpisy w Autenti → webhook → finalny PDF w CRM.

**Stan: prototyp integracyjny, 6 września 2026.** Adapter korzysta z udokumentowanego Public API V2. Przetestowano lokalną logikę i kontrakt HTTP z atrapą Autenti oraz prawdziwą weryfikację RSA/JWS. Nie wykonano rzeczywistej wysyłki na Twoim koncie, ponieważ nie przekazałeś konfiguracji i nie były dostępne tokeny. Wprowadzenie prawidłowych danych nie zastępuje uprawnień organizacji ani aktywacji usług.

## 1. Co otrzymujesz

- Dwa główne formularze: klienci oraz opcjonalny przedstawiciel dewelopera. Możesz dodać do 10 klientów, każdy z innym e-mailem.
- Podgląd PDF z automatycznie podstawionymi danymi i polskimi znakami.
- DEMO bez sieci oraz LIVE z faktycznymi wywołaniami Autenti.
- Ekran konfiguracji zamiast obowiązkowej edycji kodu.
- OAuth2 przez konto użytkownika, client_credentials, gotowy bearer token, refresh token lub API key.
- Wysyłkę do wszystkich osób z rolą SIGNER. Wiadomości wysyła Autenti, więc nie konfigurujesz SMTP.
- Podpisany webhook, trwałą kolejkę zdarzeń w SQLite i pobranie SIGNED_CONTENT_FILE po stanie COMPLETED.
- Ręczny przycisk sprawdzenia stanu bez ponownego wysyłania.
- Lokalne blokowanie duplikatów tej samej próby i zachowanie ID procesu po błędzie.

PDF jest **technicznym dokumentem testowym**, a nie opracowaną prawnie umową rezerwacyjną. Jest celowo oznaczony. Przy pominięciu dewelopera test obejmuje podpis klienta, nie kompletną dwustronną umowę. Gotową treść dewelopera należy później wdrożyć w `documents.py`; nie usuwaj oznaczenia testowego z niezatwierdzonego szablonu.

## 2. Uruchomienie na Macu

1. Rozpakuj ZIP, np. do `~/Downloads/autenti-crm-prototype`.
2. Zainstaluj Python 3.11 lub nowszy, jeśli nie masz go na komputerze: [python.org – macOS](https://www.python.org/downloads/macos/). Aplikacja nie wymaga Dockera, Node.js ani bazy danych instalowanej osobno.
3. Otwórz Terminal i wykonaj:

```bash
cd ~/Downloads/autenti-crm-prototype # Wejdź do folderu; dostosuj ścieżkę, jeśli rozpakowałeś gdzie indziej.
bash start-mac.command # Utwórz .venv, zainstaluj pakiety i uruchom oba lokalne serwery.
```

4. Otwórz w swojej przeglądarce `http://127.0.0.1:8000`.
5. Pozostaw Terminal otwarty. Zatrzymanie: `Ctrl+C`. Ponowny start: ta sama komenda. Dane pozostają w katalogu `data/`.

Alternatywny start ręczny:

```bash
python3 -m venv .venv # Utwórz izolowane środowisko.
source .venv/bin/activate # Włącz środowisko w tym terminalu.
python -m pip install -r requirements.txt # Zainstaluj zależności.
python app.py # Uruchom panel 8000 i odbiornik 8001.
```

Skrypt jest przeznaczony dla macOS Intel i Apple Silicon z Pythonem 3.11+. Test wykonano tutaj na Linuxie/Pythonie 3.12; nie wykonano testu na fizycznym Macu.

## 2a. Uruchomienie na Windows 10/11

To ta sama aplikacja i identyczne funkcje API, z osobnym skryptem startowym dla Windows.

1. Zainstaluj Python 3.11 lub nowszy z [python.org](https://www.python.org/downloads/windows/). W instalatorze zaznacz **Add python.exe to PATH**.
2. Pobierz repozytorium przez **Code → Download ZIP** i rozpakuj je w swoim folderze użytkownika. Nie uruchamiaj plików wewnątrz ZIP.
3. Kliknij dwukrotnie `start-windows.cmd`. Skrypt tworzy `.venv`, instaluje zależności i uruchamia aplikację. Nie wymaga administratora ani zmiany polityki PowerShell.
4. Otwórz `http://127.0.0.1:8000`. Pozostaw okno skryptu otwarte. Zatrzymanie: `Ctrl+C`.
5. Pobierz ngrok dla Windows ze strony ngrok.com i rozpakuj `ngrok.exe`. Otwórz PowerShell w folderze z tym plikiem i wykonaj:

```powershell
.\ngrok.exe config add-authtoken "TWOJ_TOKEN_NGROK" # Zapisz token konta ngrok.
.\ngrok.exe http 8001 # Wystaw tylko odbiornik webhooka i OAuth.
```

Dalsza konfiguracja, adresy webhooka i OAuth, tryby podpisu oraz testy są identyczne z opisem poniżej. Nie kopiuj `.venv` pomiędzy Maciem i Windowsem. Każdy komputer tworzy własne środowisko. Testów na rzeczywistym Windowsie nie wykonano.

## 3. Najpierw test bez kluczy

1. Domyślnie działa DEMO/ACCEPT.
2. Kliknij „Wstaw przykładowe dane”. Są fikcyjne; adresy `example.com` nie są skrzynkami do testu wysyłki.
3. W razie potrzeby dodaj kolejnych klientów.
4. Aby podpisał też przedstawiciel, zaznacz „Dodaj podpis przedstawiciela”. Bez zaznaczenia jego pola nie są wymagane i nie trafia on do procesu.
5. Kliknij „Pobierz podgląd PDF”. Sprawdź treść i polskie znaki.
6. Kliknij „Utwórz demonstrację”. Dokument trafi do historii jako DEMO_READY. **Nie będzie e-maila, certyfikatu ani fikcyjnego podpisu.**

## 4. Uruchom ngrok – wyłącznie port 8001

Jeżeli masz Homebrew:

```bash
brew install ngrok # Zainstaluj oficjalnego agenta tunelu.
ngrok config add-authtoken "TWOJ_TOKEN_NGROK" # Wpisz token konta ngrok, nie token Autenti.
ngrok http 8001 # Udostępnij odbiornik webhooka i callback OAuth.
```

Możesz też pobrać instalator zgodnie z [oficjalną instrukcją ngrok dla macOS](https://ngrok.com/download/mac-os).

Ngrok pokaże publiczny adres HTTPS. Jeśli będzie to `https://twoja-domena.ngrok-free.app`, ustaw:

| Pole | Wartość w tym przykładzie |
|---|---|
| Webhook URL | `https://twoja-domena.ngrok-free.app/webhooks/autenti` |
| OAuth redirect URL | `https://twoja-domena.ngrok-free.app/oauth/callback` |
| Kontrola tunelu | `https://twoja-domena.ngrok-free.app/health` |

Podmień domenę na faktyczną z ngrok. `/health` zwróci status bez danych. Publiczne `/api/config` i `/` nie udostępniają panelu. **Nie tuneluj portu 8000.** W ngrok mogą być widoczne żądania webhooków i callback OAuth, dlatego traktuj dostęp do panelu inspekcji tunelu jako prywatny. Ngrok token zapisujesz tylko w narzędziu ngrok, nie w aplikacji CRM.

Komputer, aplikacja i ngrok muszą działać podczas odbioru. Jeśli adres tunelu się zmieni, zaktualizuj konfigurację, whitelistę OAuth i callback w Autenti. Przycisk rejestracji nie usuwa starych callbacków – celowo nie zmienia pozostałych integracji organizacji. Autenti dokumentuje limit 5 callbacków na organizację.

## 5. Konfiguracja Autenti

Przejdź do „Konfiguracja API”. Możesz też skopiować `config.example.json` do `config.local.json` i edytować go przy zatrzymanej aplikacji. Edycja z UI jest prostsza. Puste pole sekretu zachowuje jego poprzednią wartość; aby usunąć sekret, wyczyść odpowiednią wartość w lokalnym JSON po zatrzymaniu aplikacji.

| Pole | Znaczenie / skąd je wziąć |
|---|---|
| Tryb | `demo` nie używa sieci; `live` wykonuje rzeczywiste operacje nawet na ACCEPT. |
| Środowisko | `accept` lub `production`. Klucze i usługi muszą należeć do wybranego środowiska. |
| Client ID | Identyfikator utworzonej aplikacji API Autenti; to nie NIP ani ID klienta kupującego lokal. |
| Client secret | Sekret tej aplikacji. Nie wpisuj hasła do konta Autenti. |
| Auth mode | Wybierz dokładnie jeden opisany niżej sposób autoryzacji. |
| Access token | Opcjonalnie gotowy token OAuth2; bez prefiksu `Bearer`. |
| Refresh token | Opcjonalnie token otrzymany po autoryzacji. Jest rotowany; nie używaj równolegle tego samego tokenu w Postmanie. |
| API key | Alternatywny klucz, wyłącznie jeśli Autenti faktycznie go wydało. Nie jest to client secret. |
| Scope | Zakresy dozwolone dla aplikacji. Puste pole pomija scope przy tokenach; logowanie interaktywne domyślnie prosi o `full`, jak przykład dokumentacji. Wpisz węższe zakresy uzgodnione z Autenti, jeśli wymagane. |
| Wysyłaj jako organizacja | Dodaje `PARTY-TENANT:SELF` / `SENDER`. Wymaga osobnej aktywacji. Przy zwykłym użytkownikowym OAuth nadawcę można pozostawić domyślnego. |
| Webhook URL | Publiczny HTTPS ngrok z końcówką `/webhooks/autenti`. |
| Management token | Opcjonalny bearer token Superadministratora z `notification_management`; służy rejestracji callbacka. Gdy puste, wykorzystywana jest bieżąca autoryzacja. |
| OAuth redirect URL | Publiczny adres ngrok z `/oauth/callback`, wpisany dokładnie na whitelistę aplikacji w Autenti. |
| QES issuance enabled | Twoje potwierdzenie, że Autenti aktywowało jednorazowe QES na koszt nadawcy. Samo zaznaczenie nie aktywuje usługi. |
| Profile constraints | Tablice JSON wymuszające metody udostępnione dla organizacji przez Autenti; szczegóły poniżej. |

Adresy backendu są zdefiniowane w `autenti.py`, zgodnie z dokumentacją:

- ACCEPT: `https://api.accept.autenti.net/api/v2`
- Produkcja: `https://api.autenti.com/api/v2`

JWKS jest wybierany automatycznie. **Nie trzeba wpisywać webhook secret**, ponieważ Autenti podpisuje powiadomienia JWS, a aplikacja weryfikuje je publicznym kluczem Autenti. Nie potrzebujesz własnego klucza do wystawiania certyfikatów kwalifikowanych. Jeśli masz indywidualny endpoint lub inny model autoryzacji, adapter wymaga dostosowania; nie wysyłaj kluczy do przypadkowych hostów.

## 6. Wybierz sposób połączenia

### A. Logowanie kontem Autenti – przydatne do pierwszego testu

1. W Autenti, w konfiguracji Twojej aplikacji API, dodaj do dozwolonych redirect URL dokładnie adres `https://TWOJA-DOMENA/oauth/callback`.
2. Upewnij się, że aplikacja ma uprawnienia do tworzenia, wysyłania i odczytywania dokumentów, a konto ma właściwy pakiet.
3. W prototypie ustaw LIVE, ACCEPT, wpisz Client ID, Client secret i OAuth redirect URL. Możesz pozostawić auth mode do czasu logowania – po sukcesie zmieni się automatycznie na `refresh_token`.
4. Zapisz konfigurację. Upewnij się, że ngrok działa na porcie 8001.
5. Kliknij „Zaloguj się przez Autenti”. Przeglądarka przejdzie do Autenti. Logowanie i MFA odbywają się po stronie Autenti.
6. Po udanym callbacku zamknij tę kartę lub wróć do lokalnego panelu i odśwież go. Tokeny zostały zapisane lokalnie, nie są wyświetlane.
7. Kliknij „Sprawdź zapisane połączenie”. Sukces oznacza uwierzytelnienie i dostęp do odczytu, nie pełną aktywację QES.

Przy odmowie grantu, scope lub whitelisty popraw konfigurację po stronie Autenti. Prototyp obsługuje udokumentowany OAuth2 authorization_code z `state`, wymianą kodu na backendzie i rotacją refresh tokenu. Autenti może wymagać ponownego logowania; aplikacja nie omija MFA/challenges. To wariant użytkownikowy, nie potwierdzenie docelowego modelu VAR/M2M.

### B. Serwer–serwer client_credentials

Wybierz client_credentials, uzupełnij Client ID i secret, zapisz i sprawdź połączenie. Ten wariant wymaga odpowiednich uprawnień M2M/Enterprise/BPA przyznanych przez Autenti. Sam token może nie mieć prawa wysyłki lub odczytu dokumentów. Jeżeli nie działa, nie dodawaj przypadkowych scope – uzgodnij je z Autenti albo użyj wariantu A do testu użytkownikowego. Włączenie nadawcy organizacyjnego też wymaga aktywacji.

### C. Token z oficjalnego Postmana lub API key

Możesz wybrać bearer i wkleić access_token uzyskany legalnie dla własnej aplikacji/konta, np. z [oficjalnej kolekcji Autenti](https://www.postman.com/autenti-api/autenti-api/documentation/uzn9w70/autenti-api-v2). Przy wygaśnięciu trzeba go zastąpić. Alternatywnie wybierz refresh_token i podaj Client ID, secret i refresh token. Wariant api_key wysyła `Authorization: api-key ...`, a nie Bearer. Wymiana partnerska token-exchange, JWT bearer z własnym kluczem i indywidualne szablony BPA nie są zaimplementowane w tym prototypie.

## 7. Rejestracja webhooka

1. Wpisz i zapisz URL webhooka, pozostawiając aplikację i ngrok uruchomione.
2. Jeśli bieżąca autoryzacja nie ma uprawnień administracyjnych, uzupełnij Management token uprawnionego Superadministratora i zapisz.
3. Kliknij „Zarejestruj zapisany webhook”. Aplikacja najpierw sprawdzi listę callbacków, a potem ewentualnie doda swój URL.
4. Jeżeli callback istnieje, aplikacja nie dodaje duplikatu.
5. Jeżeli Autenti zwraca 403, sprawdź `notification_management` oraz uprawnienie zarządzania powiadomieniami aplikacji. Uprawnienia muszą być właściwe zarówno dla aplikacji, jak i kontekstu użytkownika.

Webhook w tej wersji korzysta z `x-jws-signature`, RS256 i właściwego zestawu kluczy dla środowiska. Nie używa wyłącznika weryfikacji. Ręczne wysłanie zwykłego JSON przez curl powinno dać 401. Po poprawnej weryfikacji zdarzenie jest zapisywane do SQLite, a worker odczytuje proces i pobiera wynik. Powtórzony event ma ponownie odpowiedź 200, lecz nie duplikuje kolejki.

## 8. Rodzaje podpisów – co rzeczywiście obsługuje prototyp

| Wybór | Działanie adaptera | Co musi zapewnić Autenti |
|---|---|---|
| Zwykły elektroniczny | Jawnie wymusza `SIGNATURE_PROVIDER-SIGNATURE_TYPE:BASIC`. | Możliwość wysłania i podpisania dokumentu w organizacji. |
| QES | Jawnie wymusza `SIGNATURE_PROVIDER-SIGNATURE_TYPE:QUALIFIED`. | Wydanie jednorazowego certyfikatu odbiorcy na koszt nadawcy oraz odpowiedni proces płatności. |
| Podpis z identyfikacją mObywatel | Dodaje przekazane przez Ciebie constraints uczestnika. Bez profilu blokuje LIVE. | Potwierdzenie takiego procesu, jego poziomu podpisu i konkretnych constraints API V2. |
| QES + mObywatel | Wymusza QUALIFIED i dodaje profil constraints od Autenti. Bez profilu blokuje LIVE. | Aktywacja np. Autenti by Cencert One Shot i konfiguracja wyboru tej metody. |

**mObywatel jest metodą identyfikacji w określonym procesie, nie samodzielnym poziomem podpisu.** Nie ma tu wymyślonego parametru `mobywatel=true`. BASIC nie jest automatycznie zamieniany na QES. Wszyscy podpisujący dostają metodę wybraną dla tego dokumentu.

Prototyp pokazuje wszystkie zamówione opcje, ale nie udaje aktywacji dostawcy. Nie potwierdzono publicznego uniwersalnego profilu pozwalającego przełączyć mObywatel dla dowolnej aplikacji API. Poproś Autenti o **działającą tablicę constraints dla uczestnika Public API V2** i wklej ją w odpowiednie pole. Nie wklejaj całego żądania ani sekretów. Pole QES pozwala dodatkowo ograniczyć dostawcę; bez tego dostępne opcje wybiera konfiguracja Autenti.

Jeżeli Autenti udostępnia Twój wariant wyłącznie przez **BPA z indywidualnym szablonem**, to potrzebny jest osobny adapter do tego konkretnego szablonu i jego schematu. Ta paczka go nie implementuje, ponieważ nie udostępniono jego identyfikatora ani kontraktu. Same klucze API nie uzupełnią tej luki. Nie traktuj tego jako przetestowanej integracji mObywatel.

Domyślny wybór BASIC służy sprawdzeniu technicznej wysyłki, nie ocenie, czy wystarcza dla konkretnej umowy rezerwacyjnej. Przed użyciem biznesowym wybór formy podpisu i szablon musi odpowiadać wymaganiom danej umowy.

## 9. Pierwsza prawdziwa wysyłka na ACCEPT

1. Zaloguj aplikację albo skonfiguruj dopuszczony przez Autenti tryb serwerowy.
2. Sprawdź połączenie i zarejestruj webhook.
3. W formularzu wpisz swoje faktyczne adresy testowe – każda osoba osobny e-mail. Przy kilku klientach użyj „Dodaj klienta”.
4. Dla testu dwustronnego zaznacz przedstawiciela dewelopera i uzupełnij jego imię, nazwisko oraz e-mail. Sama nazwa firmy nie jest podpisującym.
5. Zacznij od BASIC, żeby odseparować problem API od aktywacji jednorazowego QES.
6. Pobierz podgląd i sprawdź, czy wszystkie osoby i lokal są poprawne.
7. Kliknij „Wyślij zaproszenia przez Autenti”. Potwierdzenie pokaże adresy odbiorców i środowisko.
8. Prototyp tworzy DRAFT, dodaje PDF i wykonuje akcję DOCUMENT_SENT. **SENT oznacza potwierdzoną akcję wysyłki, nie dowód dostarczenia wiadomości.**
9. Sprawdź skrzynki i spam. Na ACCEPT Autenti może mieć ograniczenia odbiorców lub symulowane metody – potwierdź to z opiekunem.
10. Każda osoba otwiera swoje zaproszenie i podpisuje w Autenti. Prototyp nie podpisuje za ludzi.
11. Po zebraniu wszystkich podpisów webhook uruchomi pobranie. W historii pojawi się „Pobierz podpisaną umowę”.
12. Gdy pliku nie ma, kliknij „Sprawdź w Autenti”. Nie wysyła to nowej umowy. Po COMPLETED finalny plik może być chwilowo niedostępny; worker ponawia jego pobranie.
13. W kolejnym teście wybierz QES dopiero po potwierdzeniu aktywacji podpisów jednorazowych. Certyfikat jest wystawiany konkretnej osobie, a konto organizacji jest płatnikiem zgodnie z umową z Autenti.

Nie musisz konfigurować linków action-links ani return URL po podpisaniu: ten scenariusz korzysta z zaproszeń wysyłanych bezpośrednio przez Autenti. OAuth redirect URL służy wyłącznie logowaniu aplikacji, a webhook odbiorowi zdarzeń – to dwa różne adresy.

## 10. Diagnostyka

| Objaw | Co sprawdzić |
|---|---|
| 401 | Właściwe środowisko, grant i ważność tokenu; w razie potrzeby ponowne logowanie. |
| 403 | Uprawnienia aplikacji/użytkownika, M2M, nadawca organizacyjny albo notification_management. |
| 402 | Pakiet, limit dokumentów, dostęp do usługi. |
| 429 | Odczekaj okres Retry-After. Nie ponawiaj wysyłki w pętli. |
| NEEDS_REVIEW | Sprawdź ID procesu i panel Autenti. Dodatkowy challenge, timeout lub brak potwierdzonej akcji wymaga oceny. |
| Nie ma ID procesu po błędzie | Utworzenie mogło nastąpić mimo przerwania połączenia. Sprawdź w Autenti, zanim rozpoczniesz nowe zlecenie. |
| Brak maila mimo SENT | Spam, poprawność adresu, ograniczenia ACCEPT i konfiguracja powiadomień Autenti. |
| QES wymaga zakupu przez klienta | Brak aktywacji właściwego wariantu wydania na koszt nadawcy; checkbox w CRM nie steruje rozliczeniem Autenti. |
| Brak mObywatela | Profil/dostawca nieaktywne, nieprawidłowe constraints albo wymagany BPA. |
| Webhook 401 | Podpis, oryginalne body i klucze ACCEPT/production; nie wyłączaj walidacji. |
| Webhook 503 | Niedostępny JWKS; Autenti może ponowić powiadomienie. |
| Brak finalnego PDF | Nie wszyscy podpisali, callback nie działa, aplikacja wyłączona, wygasły token albo finalizacja nadal trwa. |
| Port zajęty | Zamknij poprzednią instancję aplikacji korzystającą z 8000/8001. |

Nowy klik „Rozpocznij nowe zlecenie” generuje nowy identyfikator. Używaj go dopiero po sprawdzeniu poprzedniej próby. Lokalna idempotencja nie daje gwarancji exactly-once po niepewnym wyniku zewnętrznego API. Po zamknięciu karty/odświeżeniu formularza również sprawdź historię przed następną wysyłką.

## 11. Pliki i działanie kodu

| Plik | Rola |
|---|---|
| `app.py` | Panel, walidacja, konfiguracja, OAuth, SQLite, webhook i worker. |
| `autenti.py` | Uwierzytelnianie, tworzenie procesu, upload, wysyłka, status, pobranie finalnego PDF, callbacki. |
| `documents.py` | Testowy szablon PDF; miejsce na docelowy generator umowy. |
| `templates/index.html` | Formularze stron i konfiguracji. |
| `static/app.js` | Obsługa przycisków, wywołania lokalnego API, historia. |
| `static/style.css` | Responsywny interfejs. |
| `config.example.json` | Bezpieczny pusty wzór konfiguracji. |
| `config.local.json` | Twoje sekrety; tworzony przy zapisie. |
| `data/crm.sqlite` | Historia zleceń i trwała kolejka zdarzeń. |
| `data/*-source.pdf` | Dokładne dokumenty wysłane do podpisu. |
| `data/*-signed.pdf` | Oryginalne bajty finalnych dokumentów Autenti. |
| `tests/test_flow.py` | Testy kontraktu z atrapą i weryfikacji webhooka. |

Kod Python i JavaScript zawiera komentarze opisujące operacje. SQLite nie szyfruje danych. Katalog `data/` ma prawa 0700, a konfiguracja 0600; na systemach Unix ogranicza to dostęp do właściciela. Na Windows te tryby nie zapewniają odpowiednich ACL: przechowuj projekt w prywatnym folderze swojego konta Windows i ogranicz dostęp innych użytkowników uprawnieniami NTFS. Prototyp jest lokalnym narzędziem jednego operatora, bez produkcyjnej wielodostępności, portfela, fakturowania czy rozliczania tenantów CRM.

Tokeny odświeżania mają cykl życia narzucony przez Autenti. Worker zachowuje kolejkę, ale jeżeli token wymaga ponownego logowania, dokument zostanie pobrany po przywróceniu autoryzacji. Zakres obsługi challenges jest ograniczony: aplikacja nie potwierdza automatycznie nowych zgód, nie udaje sukcesu i kieruje do sprawdzenia procesu w Autenti.

Opcjonalne testy lokalne:

```bash
source .venv/bin/activate # Aktywuj środowisko aplikacji.
python -m pip install pytest # Doinstaluj runner testowy.
python -m pytest tests -q # Uruchom testy bez połączenia z Autenti.
```

## 12. GitHub

Paczka jest gotowa do umieszczenia w repozytorium. Nie wymaga GitHuba do uruchomienia. Repozytorium projektu: https://github.com/sebastian-c87/Autenti-API. Po pobraniu przez GitHub ZIP folder będzie nosił nazwę `Autenti-API-main`; dostosuj polecenie `cd` do tej nazwy. Możesz też sklonować repozytorium komendą `git clone https://github.com/sebastian-c87/Autenti-API.git`, wejść do `Autenti-API` i uruchomić `bash start-mac.command`. `.gitignore` pomija `.venv`, konfigurację z sekretami, dane i PDF-y użytkownika. Nie dodawaj ich przez `git add -f`. Przed publikacją sprawdź listę plików staged; sekrety nigdy nie powinny trafić do repozytorium.

## 13. Oficjalne źródła kontraktu

- [Public API V2 i adresy środowisk](https://developers.autenti.com/docs/autenti-public-api-v2/111e9353643f4-autenti-document-process-api)
- [OAuth Authorization Code](https://developers.autenti.com/docs/autenti-public-api-v2/a7847a3b741c6-authorization-code-grant)
- [Refresh token i ponowne logowanie](https://developers.autenti.com/docs/autenti-public-api-v2/3b0065697f838-refreshing-tokens)
- [Client credentials i ograniczenia](https://developers.autenti.com/docs/autenti-public-api-v2/ee26bb6146e09-client-credentials-grant)
- [Wymaganie BASIC](https://developers.autenti.com/docs/autenti-public-api-v2/2ba5fb048a557-requesting-basic-electronic-signature-by-autenti)
- [Wymaganie QES](https://developers.autenti.com/docs/autenti-public-api-v2/7017daed2f140-requesting-e-idas-qualified-electronic-signature)
- [Upload PDF](https://developers.autenti.com/docs/autenti-public-api-v2/906a4ce68f1ff-document-process-files)
- [Akcja wysłania dokumentu](https://developers.autenti.com/docs/autenti-public-api-v2/zb3t8s4ir23k6-document-sending-action)
- [Callbacki i weryfikacja JWS](https://developers.autenti.com/docs/autenti-public-api-v2/34j1rby56zukt-callbacks)
- [Lista i rodzaje plików](https://developers.autenti.com/docs/autenti-public-api-v2/bq2nod4bpilzk-listing-files)
- [Pobranie zawartości i kodowanie ID](https://developers.autenti.com/docs/autenti-public-api-v2/nz4nbb62g4uda-retrieving-file-content)
- [QES Cencert z mObywatelem](https://autenti.com/pl/platforma/jednorazowy-podpis-kwalifikowany-mobywatel)
- [ngrok na macOS](https://ngrok.com/download/mac-os)

Przed produkcją konieczny jest prawdziwy test E2E na Twojej konfiguracji: wszystkie osoby otrzymują maile, właściwe certyfikaty są wydawane i opłacane zgodnie z umową, wszystkie podpisy są obecne w finalnym PDF, a wynik wraca do właściwego rekordu CRM. Sama informacja COMPLETED nie jest niezależną walidacją prawną/kwalifikowaną podpisów; aplikacja nie implementuje kwalifikowanego walidatora.
