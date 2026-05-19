# puppet-ticket-watcher

Каждые ~10 минут опрашивает страницу спектакля "Записки юного врача" на сайте
Минского театра кукол и звонит на телефон через Twilio, если появилась дата
показа позже последней известной.

URL: https://puppet-minsk.by/spektakli/spektakli-dlya-vzroslykh/item/217-zapiski-yunogo-vracha

## Как это работает

1. `watcher.py` скачивает страницу, парсит блоки `div.date-item` и извлекает даты.
2. Сравнивает максимальную дату с тем, что записано в `state.json`.
3. Если на сайте появилась дата позже сохранённой — инициирует звонок через
   Twilio голосом Polly.Tatyana с сообщением на русском (повторяется 3 раза).
4. Обновляет `state.json`.

GitHub Actions workflow `.github/workflows/check.yml` запускает скрипт по cron
`*/10 * * * *` и коммитит обновлённый `state.json` обратно в репозиторий.

> **Важно про cron в GitHub Actions:** интервалы обещаны "best effort". При
> высокой нагрузке запуск может задержаться на 5–20 минут. Для нашей задачи
> (ловить новую дату, которая висит уже пару минут) этого хватает.

## Первичная настройка

### 1. Залить в GitHub

```powershell
cd C:\Users\LobanM\puppet-ticket-watcher
git init
git add .
git commit -m "init"
# создай приватный репо на github.com, потом:
git remote add origin git@github.com:<your-user>/puppet-ticket-watcher.git
git branch -M main
git push -u origin main
```

### 2. Зарегистрироваться в Twilio

1. https://www.twilio.com/try-twilio — бесплатный триал даёт ~$15 кредита и
   один номер.
2. В консоли Twilio: **Phone Numbers → Manage → Buy a number** (триал-кредит
   покроет первый месяц).
3. **Verified Caller IDs**: на триале можно звонить только на верифицированные
   номера. Добавь свой номер, подтверди кодом.
4. Скопируй из дашборда:
   - **Account SID**
   - **Auth Token**
   - купленный **Twilio phone number** (формат `+1...`)

### 3. Добавить секреты в GitHub

`Settings → Secrets and variables → Actions → New repository secret`:

| Имя | Значение |
|---|---|
| `TWILIO_ACCOUNT_SID` | `ACxxxx...` |
| `TWILIO_AUTH_TOKEN` | `<auth token>` |
| `TWILIO_FROM` | `+1XXXXXXXXXX` (купленный номер) |
| `TWILIO_TO` | `+375XXXXXXXXX` (твой номер в международном формате) |

### 4. Проверить, что всё работает

В GitHub: `Actions → Check tickets → Run workflow` — запусти вручную. Должен
завершиться зелёным. Лог покажет `Found 6 dates. Latest on site: 2026-07-22.`

Чтобы реально проверить звонок, временно подправь `state.json` (поставь
`"latest_date": "2026-06-01"`), закоммить, запусти workflow вручную. Должен
зазвонить телефон. После теста верни `state.json` обратно к актуальной
последней дате (`2026-07-22`).

## Локальный запуск

```powershell
cd C:\Users\LobanM\puppet-ticket-watcher
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# без звонка — просто проверка парсинга:
python watcher.py

# со звонком — задай переменные окружения:
$env:TWILIO_ACCOUNT_SID = "ACxxxx"
$env:TWILIO_AUTH_TOKEN  = "xxxx"
$env:TWILIO_FROM        = "+1XXXXXXXXXX"
$env:TWILIO_TO          = "+375XXXXXXXXX"
python watcher.py
```

## Что делать после того, как зазвонит

1. Сразу открыть https://puppet-minsk.by/spektakli/spektakli-dlya-vzroslykh/item/217-zapiski-yunogo-vracha
2. На странице найти новый блок `div.date-item` → кнопка **Купить у нас**
   ведёт на tce.by, либо **ticketpro.by**.
3. После покупки можно отключить workflow: `Actions → Check tickets → ... → Disable workflow`.

## Если сайт поменяет вёрстку

Скрипт ищет даты по селектору `div.date-item div.date-time p` и регулярке
`(\d{1,2})\s+([А-Яа-яёЁ]+),\s*[А-Яа-яёЁ]+,\s*(\d{1,2}):(\d{2})`. Если перестанет
парсить — `watcher.py` вернёт код 1, workflow покраснеет, и придёт письмо от
GitHub. Тогда нужно посмотреть текущий HTML и поправить селектор/регулярку.
