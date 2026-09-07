const form = document.getElementById('chat-form');
const input = document.getElementById('message-input');
const messages = document.getElementById('messages');
const status = document.getElementById('status');
const button = document.getElementById('send-button');
const modelName = document.getElementById('model-name');
const defaultModelName = 'gpt-5';

function appendMessage(kind, author, text) {
  const item = document.createElement('div');
  item.className = `message ${kind}`;

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
  item.append(avatar, bubble);
  messages.appendChild(item);
  item.scrollIntoView({ block: 'end', behavior: 'smooth' });
}

function setLoading(isLoading) {
  button.disabled = isLoading;
  input.disabled = isLoading;
  status.textContent = isLoading ? 'Запрос...' : 'Готов';
}

async function loadConfig() {
  try {
    const response = await fetch('/api/config');
    const data = await response.json();
    modelName.textContent = data.model || defaultModelName;
  } catch (error) {
    modelName.textContent = defaultModelName;
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
      body: JSON.stringify({ message: text }),
    });
    const data = await response.json();

    if (!response.ok) {
      appendMessage('error', 'Ошибка', data.error || 'Не удалось получить ответ агента.');
      return;
    }

    appendMessage('agent', 'Агент', data.answer);
  } catch (error) {
    appendMessage('error', 'Ошибка', 'Не удалось подключиться к web-серверу.');
  } finally {
    setLoading(false);
    input.focus();
  }
});

loadConfig();
