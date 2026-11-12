// 매일 회화 — daily conversation sentences (English / Argentine Spanish)
const UNLOCK_HOUR_KST = 7;
const TZ = 'Asia/Seoul';

const LANGS = {
  en: { name: 'English', flag: '🇺🇸', speech: ['en-US', 'en'] },
  es: { name: 'Español (Argentina)', flag: '🇦🇷', speech: ['es-AR', 'es-419', 'es-US', 'es-MX', 'es'] },
};

// ---------- persistent store (localStorage, per device) ----------
const store = {
  _read(key, fallback) {
    try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; }
  },
  _write(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
  get settings() { return { hideTranslation: true, rate: 1, voices: {}, ...this._read('settings', {}) }; },
  set settings(v) { this._write('settings', v); },
  get done() { return this._read('done', {}); },          // { sentenceId: timestamp }
  set done(v) { this._write('done', v); },
  get favorites() { return this._read('favorites', {}); }, // { sentenceId: {lang,date,text,translation} }
  set favorites(v) { this._write('favorites', v); },
  get tab() { return this._read('tab', 'en'); },
  set tab(v) { this._write('tab', v); },
};

// ---------- date helpers (everything in KST) ----------
function kstDateString(date) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
}
/** The "learning day": content for date D unlocks at D 07:00 KST. */
function learningDate(now = new Date()) {
  return kstDateString(new Date(now.getTime() - UNLOCK_HOUR_KST * 3600e3));
}
function nextUnlock(now = new Date()) {
  const [y, m, d] = learningDate(now).split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + 1, UNLOCK_HOUR_KST - 9)); // KST = UTC+9
}
function prettyDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d, 3));
  const wd = new Intl.DateTimeFormat('ko-KR', { timeZone: TZ, weekday: 'short' }).format(dt);
  return `${m}월 ${d}일 (${wd})`;
}
function untilText(target) {
  const mins = Math.max(0, Math.round((target - Date.now()) / 60000));
  const h = Math.floor(mins / 60), m = mins % 60;
  return h ? `${h}시간 ${m}분 후` : `${m}분 후`;
}

// ---------- content ----------
const cache = new Map();
async function getJSON(path) {
  if (cache.has(path)) return cache.get(path);
  const p = fetch(path, { cache: 'no-cache' }).then(r => {
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  });
  cache.set(path, p);
  p.catch(() => cache.delete(path));
  return p;
}
const getIndex = () => getJSON('content/index.json');
const getDay = (lang, date) => getJSON(`content/${lang}/${date}.json`);

/** Dates the user may see for a language (unlocked ones), newest first. */
async function unlockedDates(lang) {
  const idx = await getIndex();
  const today = learningDate();
  return (idx[lang] || []).filter(d => d <= today).sort().reverse();
}

// ---------- speech ----------
let voices = [];
function loadVoices() { voices = window.speechSynthesis ? speechSynthesis.getVoices() : []; }
if (window.speechSynthesis) {
  loadVoices();
  speechSynthesis.addEventListener?.('voiceschanged', loadVoices);
}
const norm = l => (l || '').replace('_', '-').toLowerCase();
function voicesFor(lang) {
  const base = LANGS[lang].speech.at(-1);
  return voices.filter(v => norm(v.lang).startsWith(base));
}
function pickVoice(lang) {
  const saved = store.settings.voices[lang];
  const list = voicesFor(lang);
  if (saved) { const v = list.find(v => v.voiceURI === saved); if (v) return v; }
  const quality = v => /premium|enhanced|natural|neural|google/i.test(v.name) ? 1 : 0;
  for (const pref of LANGS[lang].speech) {
    const m = list.filter(v => norm(v.lang) === norm(pref)).sort((a, b) => quality(b) - quality(a));
    if (m.length) return m[0];
  }
  return list[0] || null;
}

let currentAudio = null;
let playingBtn = null;
let currentUtterance = null; // keep a reference: iOS can garbage-collect it and never fire onend
let speakTimer = null;
function synthBusy() { return !!window.speechSynthesis && (speechSynthesis.speaking || speechSynthesis.pending); }
function stopSpeech() {
  clearTimeout(speakTimer);
  // Only cancel when something is queued: on iOS, cancel() right before speak() can swallow the new utterance.
  if (synthBusy()) speechSynthesis.cancel();
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
  if (playingBtn) { playingBtn.classList.remove('playing'); playingBtn = null; }
}
/** Play a recorded file if available, otherwise fall back to the device voice. */
function say(text, lang, { slow = false, src = null, btn = null } = {}) {
  const wasBusy = synthBusy();
  stopSpeech();
  const rate = store.settings.rate * (slow ? 0.65 : 1);
  const finish = () => { if (btn) btn.classList.remove('playing'); if (playingBtn === btn) playingBtn = null; };
  if (btn) { btn.classList.add('playing'); playingBtn = btn; }

  if (src) {
    const a = new Audio(src);
    a.playbackRate = slow ? 1 : rate; // slow version is its own file
    a.onended = finish;
    currentAudio = a;
    a.play().catch(() => { currentAudio = null; speakTTS(true); });
    return;
  }
  // Speak synchronously inside the tap (iOS requires a user gesture); if we just cancelled, give iOS a moment.
  if (wasBusy) speakTimer = setTimeout(() => speakTTS(true), 150);
  else speakTTS(true);

  function speakTTS(useVoice) {
    if (!window.speechSynthesis) { toast('이 브라우저는 음성 재생을 지원하지 않아요'); finish(); return; }
    const u = new SpeechSynthesisUtterance(text);
    const v = useVoice ? pickVoice(lang) : null;
    if (v) u.voice = v;
    u.lang = v ? v.lang : LANGS[lang].speech[0];
    u.rate = rate;
    let started = false;
    u.onstart = () => { started = true; };
    u.onend = finish;
    u.onerror = e => { if (e.error !== 'interrupted' && e.error !== 'canceled') console.warn('speech error', e.error); finish(); };
    currentUtterance = u;
    if (speechSynthesis.paused) speechSynthesis.resume(); // iOS can stay paused after the app was backgrounded
    speechSynthesis.speak(u);
    // Watchdog: if nothing starts, retry once with the system default voice, then explain.
    setTimeout(() => {
      if (started || currentUtterance !== u) return;
      if (useVoice && v) { speechSynthesis.cancel(); setTimeout(() => speakTTS(false), 150); return; }
      finish();
      toast('소리가 안 나요? 무음 모드(옆면 스위치)와 볼륨을 확인해 주세요');
    }, 1800);
  }
}

// ---------- rendering helpers ----------
const $ = sel => document.querySelector(sel);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const reEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** Wrap each glossed word/phrase in the sentence with a tappable button. */
function markWords(text, words) {
  const ranges = [];
  words
    .map((w, i) => ({ w: w.word, i }))
    .sort((a, b) => b.w.length - a.w.length)
    .forEach(({ w, i }) => {
      const re = new RegExp(`(?<![\\p{L}\\p{M}'’])${reEsc(w)}(?![\\p{L}\\p{M}'’])`, 'giu');
      for (const m of text.matchAll(re)) {
        const s = m.index, e = s + m[0].length;
        if (ranges.some(r => s < r.e && e > r.s)) continue;
        ranges.push({ s, e, i });
        break;
      }
    });
  ranges.sort((a, b) => a.s - b.s);
  let out = '', pos = 0;
  for (const r of ranges) {
    out += esc(text.slice(pos, r.s));
    out += `<button class="w" data-action="word" data-wi="${r.i}">${esc(text.slice(r.s, r.e))}</button>`;
    pos = r.e;
  }
  return out + esc(text.slice(pos));
}

let toastTimer;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2200);
}

// ---------- app state ----------
const state = {
  tab: ['en', 'es', 'review'].includes(store.tab) ? store.tab : 'en',
  viewDate: { en: null, es: null }, // null = today
  reviewLang: 'en',
  day: null,          // currently rendered day document
  revealed: new Set(),
};

async function render() {
  stopSpeech();
  document.querySelectorAll('.tab').forEach(t => t.setAttribute('aria-selected', String(t.dataset.tab === state.tab)));
  document.body.dataset.lang = state.tab === 'review' ? state.reviewLang : state.tab;
  $('#dateLabel').textContent = `${prettyDate(learningDate())} · 오늘의 회화`;
  try {
    if (state.tab === 'review') await renderReview();
    else await renderDay(state.tab);
  } catch (err) {
    console.error(err);
    $('#main').innerHTML = `<div class="locked"><div class="big">📡</div><p>콘텐츠를 불러오지 못했어요.<br>인터넷 연결을 확인한 뒤 다시 시도해 주세요.</p><button class="btn" data-action="retry">다시 시도</button></div>`;
  }
}

async function renderDay(lang) {
  const main = $('#main');
  const dates = await unlockedDates(lang);
  const today = learningDate();
  let date = state.viewDate[lang] || dates[0];
  let banner = '';

  if (!date) {
    // nothing unlocked yet (e.g. before the first day's 07:00): preview the first day
    const idx = await getIndex();
    date = (idx[lang] || []).slice().sort()[0];
    if (!date) { main.innerHTML = `<div class="locked"><div class="big">🌱</div><p>아직 준비된 문장이 없어요.</p></div>`; return; }
    banner = `<div class="banner"><span>미리보기 · ${prettyDate(date)} 오전 7시에 공개돼요</span></div>`;
  } else if (state.viewDate[lang] && date !== dates[0]) {
    banner = `<div class="banner"><span>📅 ${prettyDate(date)} 복습 중</span><button data-action="today">오늘로</button></div>`;
  } else if (date !== today) {
    banner = `<div class="banner"><span>오늘 문장을 준비 중이에요 · 최근 학습(${prettyDate(date)})을 보여 드려요</span></div>`;
  }

  const day = await getDay(lang, date);
  state.day = day;
  $('#themeLabel').textContent = `${LANGS[lang].flag} ${day.theme}`;

  const done = store.done, fav = store.favorites, hide = store.settings.hideTranslation;
  const n = day.sentences.length;
  const doneCount = day.sentences.filter(s => done[s.id]).length;

  const cards = day.sentences.map((s, si) => {
    const isDone = !!done[s.id], isFav = !!fav[s.id];
    const shown = !hide || state.revealed.has(s.id);
    return `
    <article class="card${isDone ? ' done' : ''}" data-si="${si}">
      <div class="card-head">
        <span class="chip">${esc(s.situation)}</span>
        <span class="num">${si + 1} / ${n}</span>
      </div>
      <p class="sentence" lang="${lang === 'es' ? 'es-AR' : 'en-US'}">${markWords(s.text, s.words)}</p>
      ${s.reading ? `<p class="reading">🗣️ ${esc(s.reading)}</p>` : ''}
      <button class="translation${shown ? '' : ' hidden'}" data-action="reveal">${shown ? esc(s.translation) : '👀 탭해서 뜻 보기'}</button>
      <div class="actions">
        <button class="btn primary" data-action="play">🔊 듣기</button>
        <button class="btn" data-action="slow">🐢 천천히</button>
        <span class="spacer"></span>
        <button class="btn icon${isFav ? ' on-star' : ''}" data-action="star" aria-label="즐겨찾기">${isFav ? '★' : '☆'}</button>
        <button class="btn icon${isDone ? ' on-done' : ''}" data-action="done" aria-label="학습 완료">${isDone ? '✔︎' : '✓'}</button>
      </div>
      <div class="words">
        ${s.words.map((w, wi) => `<button class="word-chip" data-action="word" data-wi="${wi}"><b>${esc(w.word)}</b><span>${esc(w.meaning.split(/[,(]/)[0].trim())}</span></button>`).join('')}
      </div>
      ${s.tip ? `<div class="tip"><span>💡</span><span>${esc(s.tip)}</span></div>` : ''}
    </article>`;
  }).join('');

  main.innerHTML = `
    ${banner}
    <div class="progress">
      <div class="progress-bar"><span style="width:${(doneCount / n) * 100}%"></span></div>
      <span>${doneCount}/${n} 완료</span>
    </div>
    ${cards}
    <div class="locked" style="padding:20px 10px">
      <p>⏰ 다음 문장 공개: 내일 오전 7시 (${untilText(nextUnlock())})</p>
    </div>`;
}

async function renderReview() {
  const lang = state.reviewLang;
  $('#themeLabel').textContent = '📚 복습';
  const dates = await unlockedDates(lang);
  const done = store.done;
  const favs = Object.entries(store.favorites).filter(([, f]) => f.lang === lang).sort((a, b) => b[1].date.localeCompare(a[1].date));

  const favRows = favs.length
    ? favs.map(([id, f]) => `
      <div class="row" data-action="fav-play" data-id="${esc(id)}">
        <div class="grow"><div class="title" lang="${lang}">${esc(f.text)}</div><div class="sub">${esc(f.translation)}</div></div>
        <span class="badge">🔊</span>
      </div>`).join('')
    : `<div class="empty">카드의 ☆를 누르면 여기에 모여요</div>`;

  const dayRows = [];
  for (const date of dates) {
    let theme = '', total = 5;
    try { const d = await getDay(lang, date); theme = d.theme; total = d.sentences.length; } catch { /* offline */ }
    const prefix = `${lang}-${date.replace(/-/g, '')}-`;
    const cnt = Object.keys(done).filter(k => k.startsWith(prefix)).length;
    dayRows.push(`
      <button class="row" data-action="open-day" data-date="${date}">
        <div class="grow"><div class="title">${prettyDate(date)}</div><div class="sub">${esc(theme)}</div></div>
        <span class="badge${cnt >= total ? ' full' : ''}">${cnt}/${total}</span>
      </button>`);
  }

  $('#main').innerHTML = `
    <div class="seg" role="group">
      <button data-action="review-lang" data-lang="en" aria-pressed="${lang === 'en'}">🇺🇸 English</button>
      <button data-action="review-lang" data-lang="es" aria-pressed="${lang === 'es'}">🇦🇷 Español</button>
    </div>
    <div class="section-title">⭐ 즐겨찾기</div>
    <div class="list">${favRows}</div>
    <div class="section-title">📅 지난 학습</div>
    <div class="list">${dayRows.join('') || '<div class="empty">아직 지난 학습이 없어요</div>'}</div>`;
}

// ---------- sheets ----------
function openSheet(html) {
  $('#sheetBody').innerHTML = html;
  $('#sheet').hidden = false; $('#sheetBackdrop').hidden = false;
}
function closeSheet() { $('#sheet').hidden = true; $('#sheetBackdrop').hidden = true; }

function openWord(lang, w) {
  openSheet(`
    <div class="sheet-head">
      <div><h2 lang="${lang}">${esc(w.word)}</h2><div class="ipa">/${esc(w.ipa)}/</div></div>
      <button class="btn primary" data-action="say-word">🔊 발음</button>
    </div>
    <dl class="kv">
      <dt>뜻</dt><dd>${esc(w.meaning)}</dd>
      <dt>품사</dt><dd>${esc(w.pos)}</dd>
      ${w.lemma ? `<dt>기본형</dt><dd lang="${lang}">${esc(w.lemma)}</dd>` : ''}
    </dl>
    ${w.note ? `<div class="note">📝 ${esc(w.note)}</div>` : ''}`);
  $('#sheetBody [data-action="say-word"]').onclick = e => say(w.word, lang, { src: w.audio, btn: e.currentTarget });
}

function openSettings() {
  const s = store.settings;
  const voiceSelect = lang => {
    const list = voicesFor(lang);
    const cur = pickVoice(lang);
    if (!list.length) return `<div class="hint">이 기기에 ${LANGS[lang].name} 음성이 없어요.</div>`;
    return `<select data-voice="${lang}">${list.map(v =>
      `<option value="${esc(v.voiceURI)}" ${cur && v.voiceURI === cur.voiceURI ? 'selected' : ''}>${esc(v.name)} (${esc(v.lang)})</option>`).join('')}</select>`;
  };
  const hasAR = voicesFor('es').some(v => norm(v.lang) === 'es-ar');
  openSheet(`
    <h2 style="font-size:22px">설정</h2>
    <div class="field switch">
      <label for="hideTr" style="margin:0">번역 가리고 시작하기</label>
      <input type="checkbox" id="hideTr" ${s.hideTranslation ? 'checked' : ''}>
    </div>
    <div class="field">
      <label for="rate">재생 속도 <span id="rateVal">${s.rate.toFixed(2)}×</span></label>
      <input type="range" id="rate" min="0.5" max="1.3" step="0.05" value="${s.rate}">
    </div>
    <div class="field">
      <label>🇺🇸 영어 음성</label>${voiceSelect('en')}
    </div>
    <div class="field">
      <label>🇦🇷 스페인어 음성</label>${voiceSelect('es')}
      <div class="hint">${hasAR ? '아르헨티나(es-AR) 음성을 사용할 수 있어요.' : '이 기기에는 아르헨티나 음성이 없어 다른 중남미 음성으로 읽어요. 곧 원어민 녹음(Azure TTS)으로 바뀔 예정이에요.'}</div>
    </div>
    <div class="field">
      <button class="btn" data-action="test-voices">🔊 음성 테스트</button>
      <div class="hint">기기 음성 ${voices.length}개 · 영어: ${esc(pickVoice('en')?.name || '기본값')} · 스페인어: ${esc(pickVoice('es')?.name || '기본값')}</div>
    </div>
    <div class="note">📱 <b>홈 화면에 설치하기</b><br>iPhone Safari에서 공유 버튼 → "홈 화면에 추가"를 누르면 앱처럼 쓸 수 있어요. 매일 오전 7시 알림은 다음 업데이트에서 추가돼요.</div>`);

  const body = $('#sheetBody');
  body.querySelector('#hideTr').onchange = e => { store.settings = { ...store.settings, hideTranslation: e.target.checked }; state.revealed.clear(); render(); };
  body.querySelector('#rate').oninput = e => {
    const rate = Number(e.target.value);
    store.settings = { ...store.settings, rate };
    body.querySelector('#rateVal').textContent = `${rate.toFixed(2)}×`;
  };
  body.querySelectorAll('[data-voice]').forEach(sel => sel.onchange = e => {
    const cur = store.settings;
    store.settings = { ...cur, voices: { ...cur.voices, [sel.dataset.voice]: e.target.value } };
  });
  body.querySelector('[data-action="test-voices"]').onclick = e => {
    const lang = state.tab === 'es' || (state.tab === 'review' && state.reviewLang === 'es') ? 'es' : 'en';
    say(lang === 'es' ? '¡Hola, che! ¿Cómo andás? Me llamo Kim.' : "Hi there! How's it going?", lang, { btn: e.currentTarget });
  };
}

// ---------- events ----------
document.querySelector('.tabs').addEventListener('click', e => {
  const t = e.target.closest('.tab'); if (!t) return;
  if (t.dataset.tab === 'review' && state.tab !== 'review') state.reviewLang = state.tab;
  state.tab = t.dataset.tab; store.tab = state.tab;
  window.scrollTo({ top: 0 });
  render();
});

$('#main').addEventListener('click', e => {
  const el = e.target.closest('[data-action]'); if (!el) return;
  const action = el.dataset.action;
  const card = el.closest('.card');
  const lang = state.tab;
  const s = card && state.day ? state.day.sentences[Number(card.dataset.si)] : null;

  switch (action) {
    case 'play': say(s.text, lang, { src: s.audio?.normal, btn: el }); break;
    case 'slow': say(s.text, lang, { slow: true, src: s.audio?.slow, btn: el }); break;
    case 'word': openWord(lang, s.words[Number(el.dataset.wi)]); break;
    case 'reveal':
      if (!store.settings.hideTranslation) break;
      state.revealed.has(s.id) ? state.revealed.delete(s.id) : state.revealed.add(s.id);
      el.classList.toggle('hidden', !state.revealed.has(s.id));
      el.textContent = state.revealed.has(s.id) ? s.translation : '👀 탭해서 뜻 보기';
      break;
    case 'star': {
      const fav = store.favorites;
      if (fav[s.id]) delete fav[s.id];
      else fav[s.id] = { lang, date: state.day.date, text: s.text, translation: s.translation, audio: s.audio?.normal || null };
      store.favorites = fav;
      el.classList.toggle('on-star', !!fav[s.id]); el.textContent = fav[s.id] ? '★' : '☆';
      toast(fav[s.id] ? '즐겨찾기에 추가했어요' : '즐겨찾기에서 뺐어요');
      break;
    }
    case 'done': {
      const done = store.done;
      if (done[s.id]) delete done[s.id]; else done[s.id] = Date.now();
      store.done = done;
      const all = state.day.sentences.every(x => done[x.id]);
      if (done[s.id] && all) toast('🎉 오늘 학습 완료!');
      render().then(() => {
        const next = document.querySelector(`.card[data-si="${Number(card.dataset.si) + 1}"]`);
        if (done[s.id] && next && !all) next.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
      break;
    }
    case 'today': state.viewDate[lang] = null; render(); break;
    case 'retry': cache.clear(); render(); break;
    case 'review-lang': state.reviewLang = el.dataset.lang; render(); break;
    case 'open-day':
      state.viewDate[state.reviewLang] = el.dataset.date;
      state.tab = state.reviewLang; store.tab = state.tab;
      window.scrollTo({ top: 0 });
      render();
      break;
    case 'fav-play': {
      const f = store.favorites[el.dataset.id];
      if (f) say(f.text, f.lang, { src: f.audio });
      break;
    }
  }
});

$('#settingsBtn').addEventListener('click', openSettings);
$('#sheetBackdrop').addEventListener('click', closeSheet);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });

// Re-render when the day rolls over at 07:00 KST (or when the app comes back to foreground).
let lastLearningDate = learningDate();
function checkRollover() {
  const ld = learningDate();
  if (ld !== lastLearningDate) {
    lastLearningDate = ld; cache.clear(); state.viewDate = { en: null, es: null }; state.revealed.clear(); render();
  }
}
setInterval(checkRollover, 60_000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) { cache.delete('content/index.json'); checkRollover(); } });

if ('serviceWorker' in navigator) {
  const hadController = !!navigator.serviceWorker.controller;
  let reloaded = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (hadController && !reloaded) { reloaded = true; location.reload(); }
  });
  navigator.serviceWorker.register('sw.js').then(r => r.update()).catch(err => console.warn('SW registration failed', err));
}
// iOS: speech can get stuck after the app returns from background
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && window.speechSynthesis && speechSynthesis.paused) speechSynthesis.cancel();
});

render();
