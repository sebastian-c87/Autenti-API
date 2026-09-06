const $ = (selector) => document.querySelector(selector); // Krótki wybór elementu.
const csrf = $('meta[name="csrf"]').content; // Token tylko lokalnego panelu.
let settings = {}; // Publiczna konfiguracja bez sekretów.
let requestId = crypto.randomUUID(); // Jedna intencja wysyłki ma stały identyfikator.
let attempted = false; // Chroni przed przypadkowym ponowieniem.
function notice(text, error=false) { $('#notice').textContent=text; $('#notice').hidden=false; $('#notice').className=error?'error':''; } // Bez wstrzykiwania HTML.
async function call(path, data) { // Wywołanie lokalnego backendu.
  const response = await fetch(path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(data)}); // Sekrety tylko w POST konfiguracji.
  const body = await response.json(); // Odpowiedź aplikacji.
  if (!response.ok) throw new Error(body.error || `Błąd HTTP ${response.status}`); // Czytelny błąd.
  return body; // Wynik bez dodatkowej interpretacji.
} // Koniec klienta API.
function addClient(person={}) { // Jeden niezależny podpisujący.
  const block=document.createElement('div'); block.className='client'; // Sekcja formularza.
  block.innerHTML='<div class="pair"><label>Imię<input name="firstName" required></label><label>Nazwisko<input name="lastName" required></label></div><label>E-mail klienta<input name="email" type="email" required placeholder="klient@example.com"></label><label>Adres · opcjonalny<input name="address" placeholder="Ulica, kod, miejscowość"></label><button type="button" class="text-button remove">Usuń klienta</button>'; // Stały HTML, bez danych użytkownika.
  for(const input of block.querySelectorAll('input')) input.value=person[input.name]||''; // Wartości są tekstem.
  block.querySelector('.remove').onclick=()=>{if($('#clients').children.length>1) block.remove();}; // Zawsze jeden klient.
  $('#clients').append(block); // Dodaj do formularza.
} // Koniec dodawania klienta.
function personFrom(element) {return Object.fromEntries([...element.querySelectorAll('input')].map(x=>[x.name,x.value.trim()]));} // Jawne pola osoby.
function formData() { // Dane niezależne od konfiguracji API.
  return {request_id:requestId,title:$('#title').value,property:$('#property').value,terms:$('#terms').value,signature:$('#signature').value,clients:[...document.querySelectorAll('.client')].map(personFrom),developer:$('#include-developer').checked?personFrom($('#developer-fields')):null}; // Wszystkie strony umowy.
} // Koniec formularza.
function methodInfo() { // Nie obiecuj niedostępnego rodzaju podpisu.
  const method=$('#signature').value; // Wybór użytkownika.
  const info={basic:'Zwykły podpis elektroniczny. Ten wariant nie wymusza QES.',qes:'Wymagany podpis kwalifikowany. Jednorazowe wydanie i koszt nadawcy muszą być aktywowane w Autenti.',mobywatel:'Metoda identyfikacji mObywatel wymaga uzgodnionego profilu Autenti. Nie jest automatycznie podpisem kwalifikowanym.',qes_mobywatel:'QES z identyfikacją mObywatel wymaga aktywnej usługi i profilu dostawcy, np. Cencert One Shot.'}; // Rzetelne rozróżnienie.
  $('#method-help').textContent=info[method]; // Wyświetl wskazówkę.
} // Koniec pomocy.
async function loadConfig() { // Sekrety nie wracają do przeglądarki.
  settings=await call('/api/config'); // Odczytaj publiczne pola.
  for(const input of $('#config-form').querySelectorAll('[name]')) { // Wypełnij kontrolki.
    if(input.type==='password') {input.value='';input.placeholder=settings.secrets_set[input.name]?'Zapisano · wpisz, aby zastąpić':'Nie ustawiono';} // Brak wartości sekretu w DOM.
    else if(input.type==='checkbox') input.checked=!!settings[input.name]; // Flagi.
    else input.value=Array.isArray(settings[input.name])?JSON.stringify(settings[input.name],null,2):settings[input.name]||''; // Profile JSON.
  } // Koniec pól.
  $('#mode').textContent=settings.mode.toUpperCase()+' / '+settings.environment.toUpperCase(); // Tryb zawsze widoczny.
  $('#send').textContent=settings.mode==='demo'?'Utwórz demonstrację':'Wyślij zaproszenia przez Autenti'; // Rozróżnienie wysyłki.
} // Koniec konfiguracji.
async function loadJobs() { // Pobierz historię lokalną, bez odpytywania Autenti.
  const jobs=await call('/api/jobs'); const container=$('#jobs');container.replaceChildren(); // Odśwież widok.
  if(!jobs.length){const p=document.createElement('p');p.className='empty';p.textContent='Nie masz jeszcze dokumentów. Zacznij od podglądu PDF.';container.append(p);} // Pusty stan.
  for(const job of jobs) { // Bez innerHTML z danymi umowy.
    const row=document.createElement('article');row.className='job';const text=document.createElement('div');const actions=document.createElement('div');actions.className='actions'; // Układ wiersza.
    const title=document.createElement('strong');title.textContent=job.title;const status=document.createElement('small');status.textContent=`${job.mode.toUpperCase()} · ${job.status} · ${job.process_id||'Brak procesu Autenti'}`;text.append(title,status); // Dokładny stan.
    if(job.mode==='demo'){const help=document.createElement('small');help.textContent='Demonstracja: nie wysłano wiadomości i nie złożono podpisów.';text.append(help);} // Nie sugeruj sukcesu LIVE.
    if(job.error){const error=document.createElement('small');error.className='error';error.textContent=job.error;text.append(error);} // Komunikat adaptera.
    for(const [kind,label] of [['source','PDF źródłowy'],...(job.final?[['signed','Pobierz podpisaną umowę']]:[])]) {const link=document.createElement('a');link.href=`/api/jobs/${encodeURIComponent(job.id)}/${kind}.pdf`;link.textContent=label;actions.append(link);} // Tylko lokalne pliki.
    if(job.process_id){const button=document.createElement('button');button.className='secondary';button.textContent='Sprawdź w Autenti';button.onclick=async()=>{button.disabled=true;try{await call(`/api/jobs/${encodeURIComponent(job.id)}/sync`,{});await loadJobs();}catch(e){notice(e.message,true);}finally{button.disabled=false;}};actions.append(button);} // Odczyt bez ponownej wysyłki.
    row.append(text,actions);container.append(row); // Renderuj wiersz.
  } // Koniec historii.
} // Koniec odświeżania.
$('#add-client').onclick=()=>{if($('#clients').children.length<10)addClient();}; // Maksymalnie dziesięć osób.
$('#include-developer').onchange=(event)=>{$('#developer-fields').disabled=!event.target.checked;}; // Pola opcjonalnego reprezentanta.
$('#signature').onchange=methodInfo; // Wyjaśnij wybraną metodę.
$('#show-contract').onclick=()=>{$('#contract-view').hidden=false;$('#config-view').hidden=true;$('#show-contract').className='active';$('#show-config').className='';}; // Zakładka umowy.
$('#show-config').onclick=()=>{$('#contract-view').hidden=true;$('#config-view').hidden=false;$('#show-config').className='active';$('#show-contract').className='';}; // Zakładka konfiguracji.
$('#sample').onclick=()=>{$('#clients').replaceChildren();addClient({firstName:'Anna',lastName:'Żółkiewska',email:'anna@example.com',address:'ul. Testowa 12, 00-001 Warszawa'});for(const input of $('#developer-fields').querySelectorAll('input'))input.value=({firstName:'Jan',lastName:'Nowak',email:'jan@example.com',company:'Deweloper Testowy sp. z o.o.'})[input.name]||'';$('#property').value='Osiedle Testowe · budynek A · lokal 12';$('#terms').value='Powierzchnia: 54 m².\nDane przykładowe do demonstracji integracji.';notice('Wstawiono fikcyjne dane. Przed LIVE zamień e-maile example.com na własne adresy testowe.');}; // Bez rzeczywistych odbiorców.
$('#preview').onclick=async()=>{ // Pobierz PDF przed wysyłką.
  if(!$('#contract-form').reportValidity())return; // Walidacja przeglądarkowa.
  try{const response=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(formData())});if(!response.ok)throw new Error((await response.json()).error);const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download='umowa-testowa.pdf';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}catch(e){notice(e.message,true);} // Bez zewnętrznej wysyłki.
}; // Koniec podglądu.
$('#contract-form').onsubmit=async(event)=>{ // Jedna świadoma wysyłka.
  event.preventDefault();if(attempted){notice('Ta próba ma już identyfikator. Sprawdź historię i Autenti przed rozpoczęciem nowego zlecenia.',true);return;} // Zapobieganie duplikatom.
  const data=formData(); // Migawka danych.
  if(settings.mode==='live'&&!confirm(`Wyślij dokument do podpisu przez Autenti (${settings.environment}) do: ${data.clients.concat(data.developer?[data.developer]:[]).map(p=>p.email).join(', ')}? Usługi mogą obciążyć konto organizacji.`))return; // Konkretni odbiorcy i skutek.
  attempted=true;$('#send').disabled=true;$('#new-attempt').hidden=false; // Nie ponawiaj po timeoutcie.
  try{const result=await call('/api/jobs',data);notice(result.error|| (result.mode==='demo'?'Demonstracja zapisana. Nie wysłano e-maili.':'Zapisano proces: '+result.status),!!result.error);await loadJobs();}catch(e){notice(e.message+' Jeśli rozpoczęto operację LIVE, sprawdź Autenti przed nową próbą.',true);}finally{$('#send').disabled=false;} // Pokazuj także błędy walidacji.
}; // Koniec wysyłki.
$('#new-attempt').onclick=()=>{if(confirm('Nowe zlecenie może utworzyć kolejną umowę. Czy sprawdzono wynik poprzedniej próby?')){requestId=crypto.randomUUID();attempted=false;$('#new-attempt').hidden=true;notice('Możesz przygotować nowe zlecenie.');}}; // Jawne rozpoczęcie kolejnego procesu.
$('#config-form').onsubmit=async(event)=>{event.preventDefault();try{const values={};for(const input of $('#config-form').querySelectorAll('[name]'))values[input.name]=input.type==='checkbox'?input.checked:input.name.endsWith('_constraints')?JSON.parse(input.value):input.value.trim();const result=await call('/api/config',values);await loadConfig();notice(result.message);}catch(e){notice(e.message,true);}}; // Zapis konfiguracji i walidacja JSON.
$('#oauth').onclick=async()=>{try{const result=await call('/api/oauth/start',{});location.assign(result.url);}catch(e){notice(e.message,true);}}; // Zaloguj się bez przekazywania hasła do CRM.
$('#check').onclick=async()=>{try{notice((await call('/api/check',{})).message);}catch(e){notice(e.message,true);}}; // Test zapisanych danych.
$('#register').onclick=async()=>{if(!confirm('Zarejestrować zapisany URL webhooka w organizacji Autenti?'))return;try{notice((await call('/api/callback',{})).message);}catch(e){notice(e.message,true);}}; // Jawna zmiana zewnętrzna.
$('#refresh').onclick=()=>loadJobs().catch(e=>notice(e.message,true)); // Ręczne odświeżenie listy.
addClient();methodInfo(); // Początkowy formularz.
Promise.all([loadConfig(),loadJobs()]).catch(e=>notice(e.message,true)); // Odczyt początkowy.
setInterval(()=>loadJobs().catch(()=>{}),10000); // Tylko lokalny stan po webhooku.
