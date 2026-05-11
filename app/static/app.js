// Vanilla JS for the fitness platform — Chart.js charts and small interactions.

document.addEventListener('DOMContentLoaded', () => {
  initLoadRecoveryChart();
  initWeightChart();
  initCalendar();
  initNutritionToggles();
  initAiChat();
});

function withChart(cb) {
  if (typeof Chart === 'undefined') {
    setTimeout(() => withChart(cb), 80);
    return;
  }
  cb();
}

function initLoadRecoveryChart() {
  const canvas = document.getElementById('loadRecoveryChart');
  if (!canvas) return;
  withChart(() => {
    const load = JSON.parse(canvas.dataset.load || '[]');
    const recovery = JSON.parse(canvas.dataset.recovery || '[]');
    const labels = load.map((d) => d.date.slice(5));
    new Chart(canvas, {
      data: {
        labels,
        datasets: [
          {
            type: 'bar',
            label: 'Нагрузка',
            data: load.map((d) => d.load),
            backgroundColor: 'rgba(91, 138, 245, 0.6)',
            borderRadius: 4,
            yAxisID: 'y',
          },
          {
            type: 'line',
            label: 'Восстановление, %',
            data: recovery.map((d) => d.nightly_recharge),
            borderColor: '#3ecf8e',
            backgroundColor: 'rgba(62, 207, 142, 0.2)',
            tension: 0.3,
            yAxisID: 'y1',
            pointRadius: 2,
          },
        ],
      },
      options: chartBaseOptions({
        y: { beginAtZero: true, ticks: { color: '#8892a8' }, grid: { color: '#1e2232' } },
        y1: {
          position: 'right',
          beginAtZero: true,
          max: 100,
          ticks: { color: '#8892a8' },
          grid: { drawOnChartArea: false },
        },
      }),
    });
  });
}

function initWeightChart() {
  const canvas = document.getElementById('weightChart');
  if (!canvas) return;
  withChart(() => {
    const data = JSON.parse(canvas.dataset.weight || '[]');
    new Chart(canvas, {
      type: 'line',
      data: {
        labels: data.map((d) => d.date.slice(5)),
        datasets: [
          {
            data: data.map((d) => d.weight_kg),
            borderColor: '#5b8af5',
            backgroundColor: 'rgba(91, 138, 245, 0.18)',
            spanGaps: true,
            tension: 0.3,
            pointRadius: 3,
            fill: true,
          },
        ],
      },
      options: chartBaseOptions({
        y: { ticks: { color: '#8892a8' }, grid: { color: '#1e2232' } },
      }, { legend: false }),
    });
  });
}

function chartBaseOptions(scales, opts = {}) {
  const showLegend = opts.legend !== false;
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: showLegend, labels: { color: '#8892a8', font: { size: 11 } } },
      tooltip: { backgroundColor: '#141720', titleColor: '#e3e6ef', bodyColor: '#e3e6ef' },
    },
    scales: Object.assign({
      x: { ticks: { color: '#8892a8' }, grid: { display: false } },
    }, scales),
  };
}

// ---------------- Calendar ----------------
function initCalendar() {
  const cells = document.querySelectorAll('.fc-cell[data-date]');
  const panel = document.getElementById('day-detail');
  if (!cells.length || !panel) return;
  const title = document.getElementById('day-detail-title');
  const body = document.getElementById('day-detail-body');
  const noteInput = document.getElementById('day-note');
  const noteStatus = document.getElementById('note-status');
  const closeBtn = document.getElementById('day-detail-close');
  const saveBtn = document.getElementById('save-note');
  let currentDate = null;

  const openDay = async (date) => {
    currentDate = date;
    panel.classList.remove('hidden');
    body.innerHTML = '<p class="muted">Загрузка...</p>';
    try {
      const res = await fetch('/day/' + date);
      const data = await res.json();
      title.textContent = data.pretty_date;
      if (!data.workouts.length) {
        body.innerHTML = '<p class="muted">День отдыха.</p>';
      } else {
        body.innerHTML = data.workouts.map((w) => `
          <div class="card" style="background:var(--card-2); padding:12px; margin: 8px 0;">
            <strong>${escapeHtml(w.sport)}</strong>
            <div class="muted">${w.distance_km} км · ${w.duration_min} мин · ❤ ${w.avg_hr} · L ${w.load_score}</div>
            <div class="muted">${w.start_time || ''}</div>
          </div>
        `).join('');
      }
      noteInput.value = data.note || '';
      noteStatus.textContent = '';
      panel.scrollIntoView({ behavior: 'smooth' });
    } catch (err) {
      body.innerHTML = '<p class="muted">Ошибка загрузки.</p>';
    }
  };

  cells.forEach((cell) => {
    const handler = () => openDay(cell.dataset.date);
    cell.addEventListener('click', handler);
    cell.addEventListener('keydown', (e) => { if (e.key === 'Enter') handler(); });
  });
  closeBtn.addEventListener('click', () => panel.classList.add('hidden'));

  const saveNote = async () => {
    if (!currentDate) return;
    saveBtn.disabled = true;
    noteStatus.textContent = 'Сохранение...';
    try {
      await fetch(`/day/${currentDate}/note`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: noteInput.value }),
      });
      noteStatus.textContent = 'Сохранено';
    } catch (err) {
      noteStatus.textContent = 'Ошибка сохранения';
    } finally {
      saveBtn.disabled = false;
    }
  };
  saveBtn.addEventListener('click', saveNote);
  noteInput.addEventListener('blur', saveNote);
}

// ---------------- Nutrition forms ----------------
function initNutritionToggles() {
  const pairs = [['toggle-food', 'food-form'], ['toggle-product', 'product-form']];
  pairs.forEach(([btnId, formId]) => {
    const btn = document.getElementById(btnId);
    const form = document.getElementById(formId);
    if (!btn || !form) return;
    btn.addEventListener('click', () => form.classList.toggle('hidden'));
  });
}

// ---------------- AI chat ----------------
function initAiChat() {
  const form = document.getElementById('chat-form');
  if (!form) return;
  const input = document.getElementById('chat-text');
  const messages = document.getElementById('chat-messages');
  const button = form.querySelector('button[type="submit"]');

  const appendMessage = (kind, text) => {
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + (kind === 'user' ? 'msg-user' : 'msg-ai');
    if (kind !== 'user') {
      const label = document.createElement('span');
      label.className = 'msg-label';
      label.textContent = 'AI тренер · по твоим данным';
      wrap.appendChild(label);
    }
    const p = document.createElement('p');
    p.textContent = text;
    wrap.appendChild(p);
    messages.appendChild(wrap);
    messages.scrollTop = messages.scrollHeight;
  };

  const send = async (text) => {
    if (!text.trim()) return;
    appendMessage('user', text);
    input.value = '';
    button.disabled = true;
    try {
      const res = await fetch('/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      appendMessage('ai', data.reply || '...');
    } catch (err) {
      appendMessage('ai', 'Ошибка: не удалось получить ответ.');
    } finally {
      button.disabled = false;
      input.focus();
    }
  };

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    send(input.value);
  });
  document.querySelectorAll('.quick').forEach((b) => {
    b.addEventListener('click', () => send(b.dataset.q || b.textContent));
  });
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
