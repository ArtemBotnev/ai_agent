# Task 27: YAML-конфигурация локальной LLM

Дата: 2026-10-08

## Что сделали

Вынесли настройки LLM и локальной Ollama-модели в отдельную конфигурационную
папку:

```text
agent_config/
  llm.yaml
  prompts/
  profiles/
  invariants/
```

## YAML config

Добавлен файл:

```text
agent_config/llm.yaml
```

Он содержит:

- active provider;
- настройки OpenAI;
- настройки Ollama;
- список доступных моделей;
- Ollama runtime options;
- пути к system prompt markdown-файлам;
- пути к memory/profile/invariants директориям.

Для Ollama добавлены самодокументируемые комментарии с диапазонами и
рекомендациями по параметрам:

```text
temperature
num_predict
num_ctx
top_k
top_p
repeat_penalty
seed
```

## Prompt files

System prompts вынесены в markdown:

```text
agent_config/prompts/ollama_system.md
agent_config/prompts/openai_system.md
```

Default chat agent использует provider-specific prompt из markdown. Внутренние
агенты summary/facts/memory/workflow продолжают использовать свои специальные
system prompts из кода.

## Profiles and invariants

Профили и invariants скопированы в новую конфигурационную структуру:

```text
agent_config/profiles/users
agent_config/invariants/users
```

Примеры также перенесены:

```text
agent_config/profiles/example/profile.md
agent_config/invariants/example/invariants.md
```

Старые дубли из `profiles/` и `invariants/` удалены. Новые пользовательские
директории `agent_config/profiles/users` и `agent_config/invariants/users`
добавлены в `.gitignore`.

## Runtime config

Добавлен загрузчик:

```text
config/agent_config.py
```

Он читает `AGENT_CONFIG_FILE` или дефолтный файл `agent_config/llm.yaml`,
валидирует базовые типы и диапазоны Ollama options.

Если `PyYAML` установлен, используется `yaml.safe_load`. Если `PyYAML` не
установлен, используется встроенный fallback-парсер для простого YAML-формата
этого проекта: секции, скаляры и списки строк.

Приоритет настроек:

```text
явный аргумент
env override
yaml config
старый дефолт
```

## Ollama API options

`OllamaLlmAgent` теперь принимает `OllamaOptions` и передаёт их в `/api/chat`
через поле:

```json
{
  "options": {
    "temperature": 0.2,
    "num_predict": 2048,
    "num_ctx": 8192
  }
}
```

## Скрипт запуска

`start_ollama_llm.sh` теперь читает модель, список моделей и base URL из
`agent_config/llm.yaml`, если они не переопределены через env.

Скрипт также печатает `AGENT_CONFIG_FILE` и сообщает, что Ollama runtime options
настраиваются в YAML.

## PyQt запуск Ollama

В PyQt UI добавлена кнопка:

```text
Запустить Ollama
```

Кнопка видна только для provider `ollama`.

Она:

- проверяет наличие команды `ollama`;
- запускает `ollama serve`, если сервер ещё не отвечает;
- ждёт готовности `/api/tags`;
- проверяет выбранную модель через `ollama list`;
- при необходимости выполняет `ollama pull <model>`.

Если сервер был запущен из UI, процесс завершается при закрытии окна.

## Response duration

В UI добавлено отображение времени ответа модели в секундах.

Для Ollama время берётся из поля API `total_duration` и переводится из
наносекунд в секунды. Если поле недоступно, используется wall-clock замер
вокруг запроса.

Для OpenAI используется wall-clock замер вокруг HTTP-запроса.

`ChatResponse` теперь содержит:

```text
duration_seconds
```

PyQt показывает это значение рядом с токенами. Web API также возвращает
`duration_seconds`, а web UI добавляет его в meta-строку ответа.

## Quantized model

В список Ollama-моделей добавлен явный квантованный тег:

```text
llama3.1:8b-instruct-q4_K_M
```

Тег `llama3.1:8b` оставлен в списке, потому что в Ollama он также указывает на
Q4_K_M-вариант.

## Проверки

Выполнены:

```text
python3 -m py_compile agent.py main.py config/agent_config.py ui/pyqt_app.py web/server.py
bash -n start_ollama_llm.sh
python3 -c "import agent, main, web.server, ui.pyqt_app, config.agent_config; print('imports ok')"
.venv/bin/python -c "import agent, main, ui.pyqt_app, config.agent_config; print('venv imports ok')"
git diff --check
```

Дополнительно проверено:

- `main.get_llm_provider()` берёт `ollama` из YAML;
- `main.get_model_name(provider="ollama")` берёт `llama3.1:8b`;
- Ollama options собираются из YAML;
- profile/invariants директории берутся из `agent_config`;
- `ChatService` собирается для Ollama со стратегией `summary`.
