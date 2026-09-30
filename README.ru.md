[English](README.md) | **Русский**

# AI Chat Exporter

> *Личный open-source проект. Создан в первую очередь для себя и опубликован на случай, если окажется полезен другим.*

![AI Chat Exporter](ui/splash.png)

Десктопное приложение для экспорта диалогов AI (**ChatGPT, Gemini, Claude, Qwen, DeepSeek**), а также двух
настраиваемых слотов **Custom 1 / Custom 2**, в локальные Markdown-файлы.
Браузерный экспорт не требует API-ключей; режим Custom API может использовать ваш собственный ключ. Без облачных сервисов, без HTTP-сервера.

## Возможности

- Экспорт диалогов **ChatGPT, Gemini, Claude, Qwen, DeepSeek**
- Слоты **Custom 1 / Custom 2**, каждый в одном из двух режимов:
  - **Web Browser Export** — экспорт произвольного веб-чата по заданным CSS-селекторам или JS
  - **API** — отправка промпта на OpenAI- или Anthropic-совместимый endpoint и сохранение ответа
- **Вкладки** провайдеров с цветовой индикацией статуса подключения
- Файлы сохраняются в `raw/<service>/*.md` — кириллица, вложения, метаданные
- Браузерный экспорт без API-ключей — работа через CDP с bundled Chromium (системный Google Chrome не требуется)
- Выбор папки экспорта; проверка обновлений; Help/About
- Экспорт всех диалогов (**Sync All**) или выбранных чатов; независимая остановка каждого провайдера
- Автономные сборки — Python и Playwright внутри приложения, ничего доустанавливать не нужно

## Скачать

- **[AIChatExporter-Setup-0.5.6.exe](https://github.com/Nordggs/Project_AI_Base/releases)** — установщик с ярлыками Desktop и Start Menu (рекомендуется)
- **[AIChatExporter-Portable-0.5.6.zip](https://github.com/Nordggs/Project_AI_Base/releases)** — портативная сборка, работает без установки

## Установка

### Вариант 1 — Установщик (рекомендуется)

1. Запустите `AIChatExporter-Setup-0.5.6.exe`
2. Следуйте инструкциям — создаются ярлыки Desktop и Start Menu
3. Запустите **AI Chat Exporter**

### Вариант 2 — Portable

Распакуйте `AIChatExporter-Portable-0.5.6.zip` в любую папку и запустите `AIChatExporter.exe`. Работает без установки.

### Из исходников

```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```

При запуске из исходников используется системный **Google Chrome** через CDP; в релизных сборках поставляется собственный bundled Chromium.

## Использование

### Общий механизм

Приложение запускает браузер (bundled Chromium или системный Chrome) с `--remote-debugging-port=9222`.
Вход в аккаунты провайдеров выполняется в открывшемся окне браузера — сессия сохраняется в профиле
(`~/.ai_pipeline/chrome_gemini`), повторный вход не требуется.

### ChatGPT / Gemini / Claude / Qwen

1. Запустите Chrome через карточку провайдера (**🚀 Запустить Chrome**)
2. Войдите в аккаунт в открывшемся окне браузера
3. Нажмите **Проверить подключение**
4. **Синхронизировать** — автоматическое сканирование сайдбара и экспорт всех диалогов

### DeepSeek

1. **Add Account** → вставьте URL чата (`https://chat.deepseek.com/a/chat/s/{uuid}`)
2. Войдите в аккаунт в открывшемся окне
3. **Sync** — экспорт диалога в `raw/deepseek/`

### Custom 1 / Custom 2

Каждый слот работает в одном из двух режимов (режим переключается во вкладке слота):

**Web Browser Export** — экспорт чата с любого сайта через общий CDP-браузер.
Знания CSS/DOM не нужны, если сайту подходит готовый preset:

1. Выберите **Web Browser Export**
2. Выберите **Preset** и нажмите **Apply preset** (поля заполнятся, останутся редактируемыми)
3. Укажите **URL** чата (можно менять после Apply — preset не привязан к одному URL)
4. **Test** — проверка preset на живой странице (счётчики + вердикт)
5. **Подключить** — подключение, затем **Сканировать** для списка чатов
6. **Синхронизировать** — экспорт выбранных чатов в `raw/`

Ручная настройка (для продвинутых): если preset не подошёл, укажите URL и CSS-селекторы
(список чатов, заголовок, сообщения, сообщения пользователя/ассистента) или JS
напрямую в полях *Advanced / Manual configuration*.

**API** — отправка промпта на OpenAI- или Anthropic-совместимый endpoint:

1. Выберите **API**
2. Укажите endpoint, модель, протокол, ключ (опционально) и системный промпт
3. **Test** — проверка подключения
4. **Generate & Save** — отправка промпта и сохранение ответа в `raw/`

> API-ключ хранится в открытом виде в локальном `config.json`.

## Формат выходного файла

```markdown
<!-- hash: e7f89a title: название чата chat_order: 0 -->

#### 👤 Вы (2024-01-15 14:30)
текст пользователя

#### 🤖 AI
текст ассистента
```

Имя файла: `{service}_{stable_id[:8]}_{hash6}.md`

## Структура проекта

```
├── main.py                      # Точка входа (pywebview UI + 2 воркера)
├── adapters/
│   ├── base.py                  # BaseAdapter ABC
│   ├── cdp_manager.py           # CDPManager (жизненный цикл браузера) + CDPContext
│   ├── chatgpt.py               # ChatGPTAdapter
│   ├── claude.py                # ClaudeAdapter
│   ├── qwen.py                  # QwenAdapter
│   ├── gemini.py                # GeminiAdapter
│   ├── deepseek.py              # DeepSeekAdapter
│   ├── custom.py                # CustomAdapter (API-режим: промпт → сохранение)
│   └── custom_web.py            # CustomWebAdapter + SelectorStrategy + ScriptStrategy
├── conversation/
│   ├── models.py                # ConversationModel (ядро)
│   ├── irbuilder.py             # IRBuilder: adapter → ConversationModel
│   ├── adapters.py              # ChatGPT __NEXT_DATA__ → ConversationModel
│   ├── enrichment.py            # Enricher: CDP-активы + runtime + blobs
│   ├── serializer.py            # сериализация
│   └── validator.py             # валидация
├── exporters/
│   ├── writer.py                # ExportWriter (atomic write, dedup, timestamps)
│   ├── gemini_extract.py        # DOM-экстракция Gemini
│   ├── chatgpt_extract.py       # DOM-экстракция ChatGPT
│   ├── claude_extract.py        # DOM-экстракция Claude
│   ├── qwen_extract.py          # DOM-экстракция Qwen
│   ├── deepseek.py              # DeepSeekExporter
│   └── attachment_capture.py    # CDP-захват вложений
├── core/
│   ├── logger.py                # LogBuffer (thread-safe)
│   ├── custom_config.py         # Custom slot config (API/Web) load/save
│   └── preset_engine.py         # Preset validation/resolution (validate/filter/path)
├── presets/
│   └── seed_presets.json        # Built-in verified presets (copied to storage on first run)
├── ui/
│   ├── app.html                 # UI layout (вкладки + слоты Custom)
│   ├── app.js                   # UI logic + pywebview bridge
│   ├── app.css                  # Styles + splash
│   └── icon.ico                 # Window icon
└── raw/                         # Выходные .md файлы
```

## Добавление preset (для разработчиков)

- Формат preset v1: `{id, name, description, default_url, version, checked_at,
  strategy{type: selector|script, navigation: goto|click,
  wait_after_click_ms (optional, по умолчанию 2000, только int > 0),
  selectors{chat_list/message/user/assistant/title/scroll},
  scripts{list_chats_js, extract_messages_js}}}`. Selector-preset не должен
  содержать `*_js` (гибрид запрещён); script-preset требует `list_chats_js`.
- Проверка: `core/preset_engine.py::validate_preset` → `(True, [])`;
  пакеты — через `filter_valid_presets`. Источник правды — код.
- Проверенные presets лежат в `presets/seed_presets.json` (при первом
  `list_presets` копируется рядом с `config.json` как `custom_presets.json`,
  никогда не перезаписывается). `checked_at` — дата живой проверки; перед
  изменением preset перепроверьте его через `check_custom_web` (счётчики + вердикт).
- Проверка применимости: `App.check_custom_web(slot, preset_id)` возвращает
  `{preset_id, page_url, chat_list_N, messages_N, user_N, assistant_N,
  scroll, verdict: Compatible|Partial|Incompatible, reason}`.

## Зависимости

- Python 3.10+ (запуск из исходников)
- `pywebview>=4.0`
- `playwright>=1.40`
- Google Chrome (только для dev-запуска; в релизных сборках — bundled Chromium)

## Известные ограничения

- CDN/blob-вложения, которые не удаётся получить, помечаются как `partial`; сам чат при этом экспортируется

## Лицензия

Проект распространяется под лицензией MIT — см. [LICENSE](LICENSE).
Сторонние компоненты (Chromium, Playwright, PyWebView и др.) — на их собственных лицензиях, см. [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
