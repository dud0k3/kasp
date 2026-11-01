# vLLM на CPU

Тестовое задание для команды исследования технологий машинного обучения.
Модель — Qwen2.5-0.5B-Instruct, vLLM 0.27.0. Сборка для ARM64, запуск только на CPU.

## Запуск

Нужны Docker, Minikube, kubectl и Python 3.12+. В Docker должно быть доступно 8 ГБ памяти.

```bash
git clone https://github.com/dud0k3/kasp.git
cd kasp
bash scripts/deploy.sh
```

Скрипт создаёт Minikube с 6 CPU и 6 ГБ памяти, собирает образы и применяет манифесты.
После запуска в отдельном терминале:

```bash
kubectl -n vllm-cpu port-forward service/vllm 8000:8000
```

API: `http://127.0.0.1:8000/v1/chat/completions`, имя модели: `qwen-cpu`.
Для запросов нужен `Authorization: Bearer <токен>`. Токен создаётся в `.secrets/api-key`.
Без него API возвращает 401.

## Что сделано

- Оба контейнера работают от пользователя 10001, без root.
- Версии зависимостей vLLM зафиксированы в `requirements.txt`. Образы закреплены по digest. Загрузчик использует только стандартную библиотеку Python.
- `initContainer` скачивает модель с HF в PVC. При следующих запусках проверяет локальные файлы без обращения к сети. Основной контейнер загружает модель из PVC в offline-режиме.
- HF-токен и API-токен передаются через Kubernetes Secret. `HF_TOKEN` и `API_KEY` можно задать через переменные окружения перед запуском. Для выбранной публичной модели HF-токен не нужен.
- `app/privacy.py` и `config/logging.json` меняют логирование: сохраняются факт запроса, статус и время. Промпты, ответы и тексты исключений в stdout/stderr не выводятся.
- Манифесты применяются через Kustomize: `kubectl apply -k k8s`.

## Настройки

Параметры модели находятся в `k8s/vllm.json`, переменные CPU — в `k8s/kustomization.yaml`.
После изменения настроек:

```bash
kubectl apply -k k8s
kubectl -n vllm-cpu rollout status deployment/vllm --timeout=900s
```

ConfigMap получает новое имя, и под перезапускается. Образ пересобирать не нужно.
Если меняется токен, нужно выполнить `python3 scripts/create_secret.py` и
`kubectl -n vllm-cpu rollout restart deployment/vllm`.

## Нагрузочный тест

С работающим port-forward:

```bash
python3 scripts/benchmark.py --requests 12 --concurrency 1 4 --output-tokens 32
```

Замеры от 1 ноября 2026 года: Apple M4, 16 ГБ RAM, лимит контейнера 4 CPU / 5 ГиБ.
BF16, KV-кэш 256 МиБ, контекст 2048, prefix caching выключен.
На каждый случай — 12 запросов по 32 выходных токена после прогрева. Все 48 запросов прошли.

| Промпт | Входных токенов | Параллельность | TTFT, с | Latency, с | Throughput, токенов/с |
|---|---:|---:|---:|---:|---:|
| Короткий | 40 | 1 | 0.253 | 2.631 | 12.16 |
| Короткий | 40 | 4 | 0.847 | 3.532 | 36.16 |
| Длинный | 1090 | 1 | 5.051 | 7.667 | 4.17 |
| Длинный | 1090 | 4 | 13.316 | 23.148 | 5.52 |

TTFT и Latency — средние значения, измеренные клиентом через streaming.
Throughput — число выходных токенов за общее время теста.
Исходные замеры: `results/benchmark.json`.

Для большого потока коротких запросов я бы увеличивал `max-num-seqs` и подбирал `max-num-batched-tokens`, чтобы обрабатывать больше запросов одним батчем. При этом нужно следить за задержкой.

Для длинных запросов я бы оставил chunked prefill, подбирал `max-num-batched-tokens` и увеличивал `kv-cache-memory-bytes`, если хватает RAM. При нехватке памяти уменьшил бы `max-num-seqs`. Для повторяющегося контекста можно включить prefix caching.
