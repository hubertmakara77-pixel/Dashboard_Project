# Dokumentacja projektu Amplifier Panel

## 1. Cel aplikacji

Aplikacja jest panelem operatorskim dla wzmacniacza/optycznego układu pomiarowego. Odczytuje dane z portu szeregowego, prezentuje je na dashboardzie, zapisuje historię, generuje warningi, pozwala ustawiać gain setpoint, obsługuje użytkowników i role, wysyła logi audit/warning do sysloga oraz pozwala eksportować historię do CSV.

Główne technologie:

- FastAPI - backend HTTP/API.
- HTML/CSS/JavaScript - frontend.
- pyserial - odczyt z portu COM.
- InfluxDB - opcjonalna historia pomiarów.
- Syslog UDP - audit i warningi.
- Plik `persisted_state.json` - trwały zapis ustawień aplikacji.

## 2. Przepływ danych

1. Urządzenie wysyła ramkę po porcie szeregowym, np.:

   ```text
   #M:CG;G:0.0;SG:0.0;PP:5.49;SPP:-999;PiA:-53.7;PiB:-53.9;PoB:-33.5;PoA:-23.6;T:29.07*
   ```

2. `serial_reader.py` odbiera linię z COM.
3. `parser.py` parsuje ramkę do słownika.
4. `serial_reader.py` uzupełnia dane:
   - dodaje `gain_set` z ostatniej wartości ustawionej przez użytkownika,
   - liczy `gain_actual`,
   - liczy `gain_delta`.
5. Dane trafiają do:
   - `state.latest_data`,
   - `state.history_buffer`,
   - InfluxDB, jeśli jest włączony.
6. Backend wystawia dane przez `/api/latest`, `/api/history`, `/api/history/export.csv`.
7. Frontend cyklicznie odświeża dashboard, wykresy, statystyki i warningi.

## 3. Format ramki pomiarowej

Aktualny parser obsługuje format:

```text
#M:CG;G:0.0;SG:0.0;PP:5.49;SPP:-999;PiA:-53.7;PiB:-53.9;PoB:-33.5;PoA:-23.6;T:29.07*
```

Zasady:

- `#` oznacza początek ramki.
- `*` oznacza koniec ramki.
- Wewnątrz ramki pola są rozdzielane średnikami.
- Klucz i wartość są rozdzielane dwukropkiem.
- `M` jest zwykłym parametrem urządzenia. Nie jest interpretowane jako początek ramki.
- `T` jest mapowane na `temperature`, bo ta nazwa jest używana w dashboardzie.
- Wartość `-999` oznacza brak danych i jest pomijana.
- Nieznane pola, jeśli mają poprawną wartość, zostają zapisane jako dodatkowe dane.

Najważniejsze pola:

- `PiA` - moc wejściowa toru A.
- `PiB` - moc wejściowa toru B.
- `PoA` - moc wyjściowa toru A.
- `PoB` - moc wyjściowa toru B.
- `T`/`temperature` - temperatura.
- `M`, `G`, `SG`, `PP`, `SPP` - dodatkowe parametry; na razie nie mają logiki sterującej, ale mogą trafiać do historii/statystyk/CSV, jeśli są obecne i nie są `-999`.

## 4. Liczenie gain

`gain_actual` jest liczony z portów:

```text
gain_a = PoA - PiA
gain_b = PoB - PiB
gain_actual = (gain_a + gain_b) / 2
```

`gain_delta` jest liczony jako:

```text
gain_delta = gain_set - gain_actual
```

`gain_set` nie jest brany z pola `SG`, ponieważ nie wiemy jeszcze, czy `SG` w protokole oznacza to samo. Aplikacja używa ostatniej wartości ustawionej przez użytkownika.

## 5. Warningi

Warningi powstają w `serial_reader.py`.

Są dwa typy warningów:

1. Gain poza tolerancją:

   ```text
   abs(gain_delta) > gain_tolerance
   ```

2. Port poza progami:

   - `PiA`,
   - `PoA`,
   - `PiB`,
   - `PoB`.

Każdy port może mieć próg `MIN` i `MAX`.

Warning zawiera:

- czas,
- pole,
- typ (`min`, `max`, `gain_tolerance`),
- aktualną wartość,
- próg,
- deltę,
- opis.

Warningi są trzymane w pamięci w `state.error_buffer`. Dashboard pokazuje licznik warningów, a zakładka `Warnings` pokazuje klasyczną tabelę.

## 6. Syslog

Syslog działa przez UDP.

Konfiguracja jest w `config.py`:

- `SYSLOG_ENABLED`,
- `SYSLOG_HOST`,
- `SYSLOG_PORT`,
- `SYSLOG_APP_NAME`,
- `SYSLOG_FACILITY`.

Są dwa typy logów:

### Warning syslog

Wysyłany, gdy pojawia się nowy aktywny warning. Jeżeli ten sam warning trwa, nie jest wysyłany ciągle w każdej ramce.

Przykład:

```text
WARNING field=PiA kind=min value=-53.70 threshold=-50.00 delta=-3.70 message="PiA below MIN threshold -50.00"
```

### Audit syslog

Wysyłany przy działaniach użytkownika:

- udane logowanie,
- nieudane logowanie,
- wylogowanie,
- ustawienie gain setpoint,
- zmiana progów warningów,
- czyszczenie warningów,
- dodanie użytkownika,
- edycja użytkownika,
- usunięcie użytkownika,
- eksport CSV.

Format:

```text
audit timestamp=...; user=...; ip=...; action=...; details=...
```

Audit zawiera:

- timestamp UTC,
- login,
- IP klienta,
- nazwę akcji,
- szczegóły akcji.

## 7. Logowanie, hasła i zabezpieczenia

### Użytkownicy

Dashboard zapisuje w `persisted_state.json` wyłącznie login, rolę i pole
`active`. Hasła są przechowywane i weryfikowane tylko przez RADIUS.

Przy pierwszej instalacji tworzone jest konto:

```text
admin / hasło losowe wypisane jednorazowo przez instalator
```

W trybie `RADIUS_MODE=local` hasło testowego konta `admin` znajduje się w
lokalnej konfiguracji FreeRADIUS i jest wypisywane przez instalator. W trybie
`RADIUS_MODE=remote` użytkownik i jego hasło muszą istnieć na centralnym
serwerze RADIUS. Sekret klienta RADIUS jest przechowywany w `.env` z
uprawnieniami `0600`.

### Role

Role:

- `Administrator`,
- `Operator`,
- `Viewer`.

Uprawnienia:

- `Administrator`: pełny dostęp, w tym Access Control.
- `Operator`: obsługa dashboardu, ustawienia gain/progów, czyszczenie warningów, eksport, wykresy/statystyki.
- `Viewer`: tylko podgląd dashboardu, wykresów, statystyk, warningów i eksport CSV.

### Active user

Pole `active` oznacza, czy konto może się logować.

- `active = true` - użytkownik może się zalogować.
- `active = false` - konto istnieje, ale logowanie jest blokowane.

To pozwala tymczasowo zablokować konto bez jego usuwania.

### Przechowywanie haseł

Dashboard nie zapisuje hasła, jego hasha ani soli. Przy uruchomieniu usuwa
również stare pola `password_hash` i `password_salt` z wcześniejszych wersji
pliku stanu. Zarządzanie hasłami odbywa się wyłącznie w RADIUS.

### Weryfikacja hasła

Podczas logowania:

1. Backend znajduje użytkownika po loginie.
2. Sprawdza, czy użytkownik istnieje.
3. Sprawdza, czy `active = true`.
4. Wysyła login i hasło do skonfigurowanego serwera RADIUS.
5. Tworzy sesję tylko po odpowiedzi `Access-Accept`.

### Sesje

Po udanym logowaniu:

1. Tworzony jest losowy token sesji przez `secrets.token_urlsafe(32)`.
2. Token jest zapisywany w pamięci serwera w `state.auth_sessions`.
3. Token trafia do przeglądarki jako cookie `session_token`.

Cookie:

- `httponly=True` - JavaScript w przeglądarce nie może odczytać tokena.
- `samesite="strict"` - ogranicza ryzyko CSRF.
- `max_age=12h` - sesja wygasa po 12 godzinach.

Ważne: sesje są trzymane tylko w pamięci. Po restarcie aplikacji użytkownicy muszą zalogować się ponownie.

### Autoryzacja endpointów

Backend nie polega wyłącznie na ukrywaniu przycisków w UI.

Każdy chroniony endpoint ma zależność `require_roles(...)`.

Przykłady:

- `/api/access/users` - tylko `Administrator`.
- `/api/set_gain` - `Administrator`, `Operator`.
- `/api/settings` - `Administrator`, `Operator`.
- `/api/latest`, `/api/history`, `/api/errors` - `Administrator`, `Operator`, `Viewer`.

Jeżeli użytkownik nie jest zalogowany, backend zwraca `401`.
Jeżeli jest zalogowany, ale nie ma roli, backend zwraca `403`.

### Ochrona ostatniego administratora

Backend blokuje:

- usunięcie ostatniego aktywnego administratora,
- zmianę roli ostatniego aktywnego administratora,
- dezaktywację ostatniego aktywnego administratora.

Dzięki temu system nie powinien zostać bez konta administracyjnego.

## 8. Eksport CSV

Endpoint:

```text
GET /api/history/export.csv
```

Obsługuje parametry:

- `range` - np. `5m`, `1h`, `24h`, `7d`, `30d`, `all`,
- `start` - opcjonalny początek zakresu ISO,
- `end` - opcjonalny koniec zakresu ISO.

Plik CSV:

- używa separatora `;`,
- zaczyna się od `sep=;`, żeby Excel w polskich ustawieniach otwierał kolumny poprawnie,
- zawiera `\r\n` jako koniec linii.

Kolumny:

- `time`,
- `M`,
- `PiA`,
- `PiB`,
- `PoA`,
- `PoB`,
- `G`,
- `SG`,
- `PP`,
- `SPP`,
- `gain_set`,
- `gain_actual`,
- `gain_delta`,
- `temperature`,
- `seq_nr`.

Eksport CSV jest logowany do sysloga jako audit.

## 9. InfluxDB

Jeżeli `INFLUX_ENABLED = True`, aplikacja próbuje zapisywać pomiary do InfluxDB.

Zapisywane są pola liczbowe z odebranej ramki oraz wartości wyliczone.

Historia dla wykresów/statystyk jest pobierana:

1. Z InfluxDB, jeśli jest dostępny.
2. Z pamięci `state.history_buffer`, jeśli InfluxDB jest wyłączony lub niedostępny.

## 10. Pliki projektu

### `config.py`

Zawiera konfigurację:

- port szeregowy,
- InfluxDB,
- plik persisted state,
- syslog.

### `parser.py`

Parsuje dane z urządzenia.

### `serial_reader.py`

Obsługuje port szeregowy, wylicza gain, wykrywa warningi i zapisuje historię.

### `state.py`

Trzyma globalny stan aplikacji, ustawienia, użytkowników, historię, warningi i sesje.

### `main.py`

Backend FastAPI: endpointy API, logowanie, role, historia, CSV.

### `influx_service.py`

Komunikacja z InfluxDB.

### `syslog_service.py`

Wysyłanie warningów i auditów do sysloga.

### `templates/index.html`

Struktura strony.

### `static/js/dashboard.js`

Logika frontendu.

### `static/css/style.css`

Wygląd panelu.

## 11. Funkcje i klasy w kodzie

### `parser.py`

#### `parse_value(value: str)`

Próbuje zamienić tekst na liczbę `float`. Jeśli się nie da, zwraca tekst. Jeśli wartość liczbowa wynosi `-999`, zwraca `None`, co oznacza brak danych.

#### `parse_semicolon_parts(payload: str, separator: str)`

Dzieli tekst po średnikach, a potem każdy fragment po separatorze (`:` albo `=`). Mapuje `T` na `temperature`. Pomija pola bez separatora i pola z wartością `None`.

#### `parse_line(line: str)`

Główna funkcja parsera. Jeśli linia ma format `#M:...*`, traktuje ją jako nową ramkę i parsuje po `:`. W przeciwnym razie obsługuje stary format `key=value`.

### `serial_reader.py`

#### `write_gain_command(ser, gain_set: float)`

Wysyła do urządzenia komendę:

```text
SET_GAIN=xx.xx
```

#### `enrich_data(data: dict)`

Uzupełnia dane pomiarowe:

- dodaje `gain_set`, jeśli go nie ma,
- liczy `gain_actual`,
- liczy `gain_delta`.

#### `is_command_response(data: dict)`

Rozpoznaje odpowiedź na komendę, a nie pomiar. Odpowiedź komendy ma `status` i nie zawiera pól pomiarowych `PiA`, `PiB`, `PoA`, `PoB`.

#### `build_limit_errors(data: dict, now: str)`

Buduje listę warningów:

- gain poza tolerancją,
- port poniżej `MIN`,
- port powyżej `MAX`.

#### `warning_key(error: dict)`

Tworzy klucz warningu `(field, kind)`. Służy do wykrycia, czy warning jest nowy, czy już trwa.

#### `format_syslog_warning(error: dict)`

Zamienia warning na tekst wysyłany do sysloga.

#### `serial_reader_loop()`

Główna pętla odczytu COM:

1. Otwiera port szeregowy.
2. Przywraca ostatni `gain_set`.
3. Czyta linie.
4. Parsuje dane.
5. Obsługuje odpowiedzi komend.
6. Uzupełnia dane.
7. Aktualizuje stan.
8. Zapisuje historię.
9. Wysyła do InfluxDB.
10. Wysyła nowe warningi do sysloga.
11. Obsługuje błędy portu.

#### `send_gain_set(gain_set: float)`

Wysyła nowy gain setpoint do urządzenia, zapisuje go jako ostatnią znaną wartość i zapisuje setpoint do InfluxDB.

### `state.py`

#### `load_persisted_state()`

Czyta `persisted_state.json`. Jeśli pliku nie ma albo jest uszkodzony, zwraca pusty słownik.

#### `merge_dashboard_settings(saved_settings: dict | None)`

Łączy ustawienia domyślne z zapisanymi. Dzięki temu brakujące pola dostają wartości domyślne.

#### `access_user_public(user: dict)`

Zwraca login, rolę i stan aktywności użytkownika. Używane w API.

#### `merge_access_users(saved_users: list[dict] | None)`

Łączy zapisanych użytkowników z domyślnym kontem. Pilnuje poprawnych pól i unikalnych loginów.

#### `save_persisted_state()`

Zapisuje do `persisted_state.json`:

- `last_known_gain_set`,
- `dashboard_settings`,
- `access_users`.

#### `save_persisted_gain_set(gain_set: float)`

Aktualizuje `last_known_gain_set` i zapisuje stan.

#### `save_persisted_dashboard_settings()`

Zapisuje aktualne ustawienia dashboardu.

#### `save_persisted_access_users()`

Zapisuje aktualną listę użytkowników.

### `main.py`

#### Klasy Pydantic

`GainSetRequest` - ciało żądania ustawienia gain.

`DashboardSettingsRequest` - ciało żądania zapisu progów warningów.

`LoginRequest` - login i hasło.

`AccessUserCreateRequest` - dane nowego użytkownika.

`AccessUserUpdateRequest` - dane edycji użytkownika.

#### `find_access_user(username: str)`

Szuka użytkownika w `state.access_users`.

#### `normalize_username(username: str)`

Czyści login ze spacji. Jeśli login jest pusty, zgłasza błąd `400`.

#### `count_active_administrators()`

Liczy aktywnych administratorów. Używane do ochrony ostatniego administratora.

#### `user_has_role(user: dict, allowed_roles: set[str])`

Sprawdza, czy użytkownik ma jedną z dozwolonych ról.

#### `get_client_ip(request)`

Pobiera IP klienta. Najpierw sprawdza `x-forwarded-for`, potem `request.client.host`.

#### `audit_event(request, action, username, details="")`

Wysyła audit event do sysloga z IP, loginem i szczegółami.

#### `create_session(username: str)`

Tworzy losowy token sesji i zapisuje go w `state.auth_sessions`.

#### `get_current_user(session_token=Cookie(...))`

Odczytuje cookie sesji, sprawdza sesję i zwraca aktualnego użytkownika. Jeśli sesja jest niepoprawna albo użytkownik jest nieaktywny, zwraca `401`.

#### `require_roles(*allowed_roles)`

Zwraca zależność FastAPI, która wymaga zalogowanego użytkownika z jedną z podanych ról.

#### `parse_iso_datetime(value)`

Parsuje datę ISO z parametrów `start`/`end`. Obsługuje także końcówkę `Z`.

#### `parse_memory_range(range_value: str)`

Zamienia zakres `5m`, `1h`, `24h`, `7d`, `30d` na czas startowy.

#### `query_history_from_memory(range_value, start=None, end=None)`

Filtruje historię z pamięci według gotowego zakresu albo widełek `start`/`end`.

#### `build_history_csv(points: list[dict])`

Buduje tekst CSV z separatorem `;`, linią `sep=;` i kolumnami pomiarowymi.

#### `lifespan(app)`

Uruchamia i zatrzymuje usługi aplikacji:

- start InfluxDB,
- start wątku serial reader,
- zatrzymanie wątku przy zamykaniu,
- zamknięcie InfluxDB.

#### Endpoint `home()`

Zwraca główną stronę `index.html`.

#### Endpoint `latest()`

Zwraca najnowsze dane pomiarowe i status portu. Dostęp: Administrator, Operator, Viewer.

#### Endpoint `status()`

Zwraca status urządzenia i konfiguracji. Dostęp: Administrator, Operator, Viewer.

#### Endpoint `get_settings()`

Zwraca ustawienia progów. Dostęp: Administrator, Operator, Viewer.

#### Endpoint `login()`

Sprawdza lokalny dostęp i rolę, zleca weryfikację hasła serwerowi RADIUS,
tworzy sesję, zapisuje cookie i wysyła audit do sysloga.

#### Endpoint `auth_me()`

Zwraca aktualnie zalogowanego użytkownika.

#### Endpoint `logout()`

Usuwa sesję, usuwa cookie i wysyła audit.

#### Endpoint `get_access_users()`

Zwraca listę użytkowników. Dostęp: Administrator.

#### Endpoint `create_access_user()`

Dodaje lokalne uprawnienie dla loginu istniejącego w RADIUS, zapisuje rolę i
wysyła audit. Dostęp: Administrator.

#### Endpoint `update_access_user()`

Aktualizuje rolę lub aktywność użytkownika. Chroni ostatniego aktywnego administratora. Dostęp: Administrator.

#### Endpoint `delete_access_user()`

Usuwa użytkownika. Chroni ostatniego użytkownika i ostatniego aktywnego administratora. Dostęp: Administrator.

#### Endpoint `update_settings()`

Zapisuje `gain_tolerance` i progi portów. Wysyła audit. Dostęp: Administrator, Operator.

#### Endpoint `get_errors()`

Zwraca listę warningów. Dostęp: Administrator, Operator, Viewer.

#### Endpoint `clear_errors()`

Czyści warningi i wysyła audit. Dostęp: Administrator, Operator.

#### Endpoint `history()`

Zwraca historię z InfluxDB albo pamięci. Obsługuje `range`, `start`, `end`. Dostęp: Administrator, Operator, Viewer.

#### Endpoint `export_history_csv()`

Eksportuje historię do CSV i wysyła audit. Dostęp: Administrator, Operator, Viewer.

#### Endpoint `set_gain()`

Wysyła nowy gain setpoint do urządzenia i wysyła audit. Dostęp: Administrator, Operator.

### `influx_service.py`

#### `init_influx()`

Inicjalizuje klienta InfluxDB, jeśli `INFLUX_ENABLED = True`.

#### `write_measurement(data: dict)`

Zapisuje pola liczbowe z pomiaru jako punkt InfluxDB.

#### `write_setpoint(gain_set: float)`

Zapisuje ustawiony gain setpoint do osobnego measurementu.

#### `get_window_for_range(range_value: str)`

Dobiera okno agregacji dla wykresu/historii, np. `1s`, `10s`, `1m`.

#### `get_flux_range(range_value: str)`

Zamienia zakres UI na zakres Flux, np. `5m` na `-5m`.

#### `get_flux_range_clause(range_value, start=None, end=None)`

Buduje fragment zapytania Flux `range(...)`, obsługując gotowe zakresy lub widełki `start`/`end`.

#### `query_history_from_influx(range_value, start=None, end=None)`

Pobiera historię z InfluxDB, filtruje pola i pivotuje je do formatu listy punktów.

#### `close_influx()`

Zamyka klienta InfluxDB.

### `syslog_service.py`

#### `send_syslog(message: str, severity: int)`

Wysyła surową wiadomość syslog UDP.

#### `send_warning(message: str)`

Wysyła warning do sysloga z severity warning.

#### `send_audit(action, username, ip_address, details="")`

Buduje i wysyła audit log z timestampem UTC, użytkownikiem, IP, akcją i szczegółami.

### `static/js/dashboard.js`

#### Funkcje formatowania

`formatDbm`, `formatDb`, `formatTemperature`, `formatTime`, `formatPlainNumber` formatują wartości do wyświetlenia.

#### `localDateTimeToIso(value)`

Zamienia lokalną wartość z pola `datetime-local` na ISO UTC.

#### `buildHistoryQuery()`

Buduje query string dla `/api/history` i eksportu CSV.

#### `syncCustomRangeInputs(sourceContainer)`

Synchronizuje pola `From/To` między zakładką Overview i Statistics.

#### `escapeHtml(value)`

Ucieka znaki HTML, żeby dane użytkowników nie wstrzykiwały kodu do tabeli.

#### `valueOrNull(input)`

Zwraca `null` dla pustego inputa albo liczbę dla wpisanej wartości.

#### `setInputValue(selector, value)`

Ustawia wartość inputa znalezionego selektorem.

#### `setTextIfExists(id, value)`

Ustawia tekst elementu, jeśli element istnieje.

#### `handleAuthResponse(response)`

Obsługuje odpowiedzi `401` i `403`. Przy `401` pokazuje ekran logowania.

#### `isAdministrator()`

Sprawdza, czy aktualny użytkownik jest administratorem.

#### `canOperate()`

Sprawdza, czy aktualny użytkownik może wykonywać operacje zapisu: Administrator lub Operator.

#### `setActiveTab(tabName)`

Przełącza aktywną zakładkę.

#### `applyRoleUi()`

Ukrywa elementy tylko dla administratora i wyłącza kontrolki zapisu dla Viewera.

#### `showLogin()`

Pokazuje ekran logowania.

#### `showApp()`

Pokazuje aplikację po zalogowaniu.

#### `loadSettings()`

Pobiera ustawienia progów z backendu.

#### `checkAuth()`

Sprawdza, czy użytkownik ma aktywną sesję.

#### `login(username, password)`

Wysyła login i hasło do backendu, zapisuje użytkownika w stanie frontendu.

#### `logout()`

Wylogowuje użytkownika.

#### `updateSettingsForm()`

Wypełnia formularz progów aktualnymi ustawieniami.

#### `saveSettings()`

Zapisuje gain setpoint, jeśli zmieniony, oraz warning thresholds.

#### `updateDashboard()`

Pobiera `/api/latest` i aktualizuje dashboard.

#### `updateWarningsTable()`

Pobiera warningi i aktualizuje licznik oraz tabelę.

#### `setupSettingsButtons()`

Podłącza kliknięcia przycisków Save i Clear.

#### `loadAccessUsers()`

Pobiera użytkowników i renderuje tabelę Access Control.

#### `getAccessRowPayload(row)`

Buduje dane do zapisu użytkownika z wiersza tabeli.

#### `setupAccessControl()`

Podłącza formularz dodawania użytkownika oraz przyciski Save/Delete w tabeli użytkowników.

#### `getLabels(points)`

Buduje etykiety czasu dla wykresów.

#### `getValues(points, field)`

Wyciąga serię wartości z historii dla danego pola.

#### `calculateStats(points, field)`

Liczy min, max, średnią i największy skok między próbkami.

#### `updateStatisticsTable()`

Pobiera historię i renderuje tabelę statystyk.

#### `createOrUpdateChart(existingChart, canvasId, labels, datasets, yLabel)`

Tworzy wykres Chart.js albo aktualizuje istniejący.

#### `updateOverviewCharts()`

Pobiera historię i aktualizuje wykresy Overview.

#### `setupRangeButtons()`

Obsługuje przyciski zakresów czasu, własne widełki `From/To` i eksport CSV.

#### `setupAuth()`

Podłącza formularz logowania i przycisk wylogowania.

#### `startDataRefresh()`

Uruchamia pierwsze pobranie danych po zalogowaniu.

## 12. Co warto pamiętać

- Dane co 10 sekund są poprawnie obsługiwane. Wykresy i statystyki będą miały rzadsze próbki.
- `M`, `G`, `SG`, `PP`, `SPP` są zachowywane, ale nie sterują jeszcze logiką aplikacji.
- `-999` nie trafia do danych jako prawdziwa wartość.
- Sesje znikają po restarcie aplikacji.
- Hasła są hashowane, świeża instalacja generuje losowe hasło administratora, a logowanie ma limit nieudanych prób.
