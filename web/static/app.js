const form = document.getElementById('chat-form');
const input = document.getElementById('message-input');
const messages = document.getElementById('messages');
const status = document.getElementById('status');
const button = document.getElementById('send-button');
const modelSelect = document.getElementById('model-select');
const defaultModelName = 'gpt-3.5-turbo-0125';

function clearMessages() {
  messages.replaceChildren();
}

function getMessageView(role) {
  if (role === 'user') {
    return { kind: 'user', author: 'Вы' };
  }

  return { kind: 'agent', author: 'Агент' };
}

function appendMessage(kind, author, text, metaText = '') {
  const item = document.createElement('div');
  item.className = 'message ' + kind;

  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.textContent = author.slice(0, 1);

  const bubble = document.createElement('div');
  bubble.className = 'message-bubble';

  const authorElement = document.createElement('span');
  authorElement.className = 'message-author';
  authorElement.textContent = author;

  const textElement = document.createElement('span');
  textElement.className = 'message-text';
  textElement.textContent = text;

  bubble.append(authorElement, textElement);
  if (metaText) {
    const metaElement = document.createElement('span');
    metaElement.className = 'message-meta';
    metaElement.textContent = metaText;
    bubble.appendChild(metaElement);
  }

  item.append(avatar, bubble);
  messages.appendChild(item);
  item.scrollIntoView({ block: 'end', behavior: 'smooth' });
}

function getResponseMeta(tokens, durationSeconds) {
  if (!tokens || typeof tokens !== 'object') {
    return '';
  }

  const currentRequest = Number(tokens.current_request);
  const history = Number(tokens.history);
  const response = Number(tokens.response);
  if (![currentRequest, history, response].every(Number.isFinite)) {
    return '';
  }

  const meta = [`Токены: запрос ${currentRequest} · история ${history} · ответ ${response}`];
  const duration = Number(durationSeconds);
  if (Number.isFinite(duration)) {
    meta.push(`время ${duration.toFixed(2)} с`);
  }

  return meta.join(' · ');
}

function setLoading(isLoading) {
  button.disabled = isLoading;
  input.disabled = isLoading;
  modelSelect.disabled = isLoading;
  status.textContent = isLoading ? 'Запрос...' : 'Готов';
}

async function loadMessages() {
  try {
    const response = await fetch('/api/messages');
    const data = await response.json();

    if (!response.ok || !Array.isArray(data.messages) || data.messages.length === 0) {
      return;
    }

    clearMessages();
    for (const message of data.messages) {
      if (!message || typeof message.content !== 'string') {
        continue;
      }

      const view = getMessageView(message.role);
      appendMessage(view.kind, view.author, message.content);
    }
  } catch (error) {
    return;
  }
}

async function loadConfig() {
  try {
    const response = await fetch('/api/config');
    const data = await response.json();
    const models = Array.isArray(data.models) ? data.models : [data.model || defaultModelName];
    modelSelect.replaceChildren();
    for (const model of models) {
      if (typeof model !== 'string' || !model.trim()) {
        continue;
      }

      const option = document.createElement('option');
      option.value = model;
      option.textContent = model;
      modelSelect.appendChild(option);
    }
    modelSelect.value = data.model || defaultModelName;
  } catch (error) {
    const option = document.createElement('option');
    option.value = defaultModelName;
    option.textContent = defaultModelName;
    modelSelect.replaceChildren(option);
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = input.value.trim();

  if (!text) {
    appendMessage('error', 'Ошибка', 'Введите непустое сообщение.');
    return;
  }

  appendMessage('user', 'Вы', text);
  input.value = '';
  setLoading(true);

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, model: modelSelect.value }),
    });
    const data = await response.json();

    if (!response.ok) {
      appendMessage('error', 'Ошибка', data.error || 'Не удалось получить ответ агента.');
      return;
    }

    appendMessage('agent', 'Агент', data.answer, getResponseMeta(data.tokens, data.duration_seconds));
  } catch (error) {
    appendMessage('error', 'Ошибка', 'Не удалось подключиться к web-серверу.');
  } finally {
    setLoading(false);
    input.focus();
  }
});

loadConfig();
loadMessages();
