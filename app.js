/* OAT Investor — Shared App Logic */

// ── Theme ────────────────────────────────────────────────────────
const THEME_KEY = 'oat-theme';

function initTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const theme = saved || 'dark';
  document.documentElement.setAttribute('data-theme', theme);
  updateThemeBtn(theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem(THEME_KEY, next);
  updateThemeBtn(next);
}

function updateThemeBtn(theme) {
  const btn = document.getElementById('theme-btn');
  if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
}

// ── Nav Active ───────────────────────────────────────────────────
function initNav() {
  const path = location.pathname.replace(/\/$/, '') || '/';
  document.querySelectorAll('.nav-links a').forEach(a => {
    const href = a.getAttribute('href').replace(/\/$/, '') || '/';
    if (path.endsWith(href) || (href !== '/' && path.includes(href.replace('.html','')))) {
      a.classList.add('active');
    }
  });
}

// ── Badges ───────────────────────────────────────────────────────
function actionBadge(action) {
  const map = {
    buy: ['badge-buy','BUY'], watch: ['badge-watch','WATCH'],
    hold: ['badge-hold','HOLD'], study: ['badge-study','STUDY'],
    sell: ['badge-sell','SELL'], starter: ['badge-starter','STARTER']
  };
  const [cls, label] = map[(action||'').toLowerCase()] || ['badge-study', action || '—'];
  return `<span class="badge ${cls}">${label}</span>`;
}

function convictionBadge(conv) {
  if (!conv) return '';
  // Normalize numeric conviction (1–5 scale) → label string
  if (typeof conv === 'number') {
    if (conv >= 5) conv = 'Very High';
    else if (conv >= 4) conv = 'High';
    else if (conv >= 3) conv = 'Medium';
    else conv = 'Low';
  }
  const c = String(conv).toLowerCase().replace(' ', '');
  if (c.includes('very') || c === 'high') return `<span class="badge badge-high">${conv}</span>`;
  if (c === 'medium') return `<span class="badge badge-medium">${conv}</span>`;
  return `<span class="badge badge-low">${conv}</span>`;
}

function tierBadge(tier) {
  if (!tier) return '';
  // Guard: ignore raw CSS-class leftovers (e.g. "waf-low"/"waf-mid") that are not real tiers
  if (/^waf-/.test(tier.trim())) return '';
  const t = tier.toLowerCase();
  const label = tier.replace(/\s*\(.*\)\s*$/, '').trim();
  let cls = 'tier-avoid';  // neutral gray default for any unrecognized tier
  if (t.includes('inevitable') && !t.includes('pre')) cls = 'tier-inevitable';
  else if (t.includes('pre')) cls = 'tier-pre-inev';
  else if (t.includes('fast')) cls = 'tier-fast';
  else if (t.includes('cyclical')) cls = 'tier-cyclical';
  else if (t.includes('turnaround')) cls = 'tier-turnaround';
  else if (t.includes('speculative')) cls = 'tier-cyclical';   // amber caution
  else if (t.includes('avoid')) cls = 'tier-turnaround';       // red — true avoid only
  // unknown tier → tier-avoid (neutral gray). NB: "Watch-Only" deprecated — use action=WATCH
  return `<span class="badge ${cls}">${label}</span>`;
}

// ── WAF Bar ──────────────────────────────────────────────────────
function wafBar(waf) {
  if (!waf) return '<span class="text-muted" style="font-size:.82rem">N/A</span>';
  const pct = Math.min(100, (waf / 10) * 100);
  const color = waf >= 7 ? '#0ECB81' : waf >= 5.5 ? '#FFE94D' : '#F6465D';
  return `
    <div class="waf-bar-wrap">
      <div class="waf-bar-track">
        <div class="waf-bar-fill" style="width:${pct}%"></div>
      </div>
      <span class="waf-score-num" style="color:${color}">${waf.toFixed(1)}</span>
    </div>`;
}

// ── Number Formatting ────────────────────────────────────────────
function fmtPrice(n) {
  if (n == null) return '—';
  return '$' + Number(n).toLocaleString('en-US', {minimumFractionDigits:0,maximumFractionDigits:2});
}

function fmtPct(n, showSign = true) {
  if (n == null) return '—';
  const sign = showSign && n > 0 ? '+' : '';
  return sign + Number(n).toFixed(1) + '%';
}

function mosPctClass(mos) {
  if (mos == null) return '';
  return mos >= 15 ? 'pos' : mos >= 0 ? '' : 'neg';
}

// ── Simple Markdown → HTML ───────────────────────────────────────
function renderMd(md) {
  if (!md) return '';
  return md
    .replace(/^#{1} (.+)$/gm, '<h1>$1</h1>')
    .replace(/^#{2} (.+)$/gm, '<h2>$1</h2>')
    .replace(/^#{3} (.+)$/gm, '<h3>$1</h3>')
    .replace(/^#{4} (.+)$/gm, '<h4>$1</h4>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/^---+$/gm, '<hr>')
    .replace(/^\- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2" target="_blank">$1</a>')
    .replace(/^(?!<[h|u|o|l|h|p|b|i|d|t])(.*\S.*)$/gm, '<p>$1</p>')
    .replace(/<p><\/p>/g, '')
    .trim();
}

// ── Tabs ─────────────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll('.tabs').forEach(tabsEl => {
    tabsEl.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const target = btn.dataset.tab;
        tabsEl.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.querySelectorAll('.tab-pane').forEach(p => {
          p.classList.toggle('active', p.id === target);
        });
      });
    });
  });
}

// ── Filters ──────────────────────────────────────────────────────
function initFilters(containerSel, itemSel, attrName) {
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const val = btn.dataset.filter;
      document.querySelectorAll(`${containerSel} ${itemSel}`).forEach(item => {
        item.style.display = (val === 'all' || item.dataset[attrName] === val) ? '' : 'none';
      });
    });
  });
}

// ── Init ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initNav();
  initTabs();
  const themeBtn = document.getElementById('theme-btn');
  if (themeBtn) themeBtn.addEventListener('click', toggleTheme);
});
