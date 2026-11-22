/* 云子域 · 前端控制台（原生 JS，无外部依赖） */
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const state = {
  token: localStorage.getItem('sdh_token') || '',
  user: null,
  config: null,
  route: { name: 'overview', params: [] },
  domainsCache: [],
};

/* ---------------- 基础 ---------------- */
function toast(msg, type = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = '.3s'; }, 2400);
  setTimeout(() => el.remove(), 2800);
}

async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (state.token) headers.Authorization = 'Bearer ' + state.token;
  const res = await fetch(path, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });
  let data = {};
  try { data = await res.json(); } catch (e) { data = {}; }
  if (!res.ok) {
    const err = new Error(data.detail || ('请求失败 ' + res.status));
    err.status = res.status;
    throw err;
  }
  return data;
}

const money = (n) => '￥' + Number(n || 0).toFixed(2);
const fmt = (iso) => (iso ? String(iso).replace('T', ' ').slice(0, 16) : '—');
const dateOnly = (iso) => (iso ? String(iso).slice(0, 10) : '—');

const STATUS = {
  pending: ['warn', '待审核'],
  active: ['ok', '已激活'],
  rejected: ['danger', '已拒绝'],
  suspended: ['danger', '已停用'],
  expired: ['info', '已过期'],
};
const statusPill = (s) => {
  const [cls, label] = STATUS[s] || ['', s || '未知'];
  return `<span class="pill ${cls}">${label}</span>`;
};

function flipStat(kind, s) {
  return s === 'active' || s === 'renew' || s === 'pending' ? '' : '';
}

function daysText(d) {
  if (!d.expires_at) return '<span class="muted">未激活</span>';
  if (d.days_left <= 0) return `<span style="color:var(--danger)">已到期</span>`;
  const cls = d.days_left <= 15 ? 'color:var(--warn)' : 'color:var(--muted)';
  return `<span style="${cls}">剩 ${d.days_left} 天</span>`;
}

async function logout() {
  try { await api('/api/auth/logout', { method: 'POST' }); } catch (e) {}
  localStorage.removeItem('sdh_token');
  state.token = ''; state.user = null;
  location.hash = '';
  render();
}

/* ---------------- 图表 ---------------- */
function lineChart(series) {
  const pts = series || [];
  const w = 1000, h = 200, padL = 22, padR = 24, padT = 18, padB = 26;
  if (!pts.length) return '<div class="empty">暂无数据</div>';
  const max = Math.max(1, ...pts.map((p) => p.count));
  const stepX = pts.length > 1 ? (w - padL - padR) / (pts.length - 1) : 0;
  const y = (v) => padT + (h - padT - padB) * (1 - v / max);
  const points = pts.map((p, i) => [padL + stepX * i, y(p.count)]);
  const path = points.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
  const area = path + ` L${points[points.length - 1][0].toFixed(1)},${h - padB} L${padL},${h - padB} Z`;
  const every = Math.ceil(pts.length / 7);
  const labels = pts.map((p, i) => {
    if (i % every !== 0 && i !== pts.length - 1) return '';
    const anchor = i === 0 ? 'start' : (i === pts.length - 1 ? 'end' : 'middle');
    return `<text x="${points[i][0].toFixed(1)}" y="${h - 7}" text-anchor="${anchor}" font-size="11" fill="#94a3b8">${p.day.slice(5)}</text>`;
  }).join('');
  const dots = points.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="4" fill="#0f766e" opacity="${i === points.length - 1 ? 1 : .3}"/>`).join('');
  return `<svg class="chart" viewBox="0 0 ${w} ${h}">
    <defs><linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#14b8a6" stop-opacity=".28"/>
      <stop offset="100%" stop-color="#14b8a6" stop-opacity="0"/>
    </linearGradient></defs>
    <path d="${area}" fill="url(#g1)"/>
    <path d="${path}" fill="none" stroke="#0f766e" stroke-width="3" stroke-linejoin="round"/>
    ${dots}${labels}
  </svg>`;
}

function barList(items, emptyText = '暂无数据') {
  if (!items || !items.length) return `<div class="empty tiny">${emptyText}</div>`;
  const max = Math.max(1, ...items.map((i) => i.count));
  return `<div class="mini-bars">` + items.map((i) => `
    <div class="mini-bar-row">
      <span class="muted" title="${esc(i.name)}">${esc(i.name.length > 22 ? i.name.slice(0, 22) + '…' : i.name)}</span>
      <div class="mini-bar-track"><div class="mini-bar-fill" style="width:${Math.round(i.count / max * 100)}%"></div></div>
      <span class="mono">${i.count}</span>
    </div>`).join('') + `</div>`;
}

/* ---------------- 登录页 ---------------- */
function renderAuth(mode = 'login') {
  const cfg = state.config || {};
  const app = $('#app');
  app.innerHTML = `
  <div class="auth-wrap">
    <div class="auth-card">
      <div class="auth-brand">
        <div class="logo-mark">云</div>
        <div><strong>${esc(cfg.site_name || '云子域')}</strong><br><small class="muted tiny">二级域名分发 · 解析托管</small></div>
      </div>
      <h1>${mode === 'login' ? '登录控制台' : '创建账号'}</h1>
      <p class="auth-sub">${mode === 'login' ? '管理你的二级域名、跳转与访问数据' : '注册后即可申请专属二级域名'}</p>
      <div class="tabs">
        <button class="${mode === 'login' ? 'on' : ''}" data-auth="login">登录</button>
        <button class="${mode === 'register' ? 'on' : ''}" data-auth="register">注册</button>
      </div>
      <form id="auth-form">
        ${mode === 'register' ? `<div class="field"><label>昵称</label><input class="input" name="name" placeholder="你的名字" required></div>` : ''}
        <div class="field"><label>邮箱</label><input class="input" name="email" type="email" placeholder="you@example.com" required></div>
        <div class="field"><label>密码</label><input class="input" name="password" type="password" placeholder="${mode === 'register' ? '至少 6 位' : '输入密码'}" required></div>
        <button class="btn primary block" type="submit">${mode === 'login' ? '登录' : '注册并登录'}</button>
      </form>
      <p class="tiny muted" style="margin-top:16px;text-align:center">
        演示账号：admin@sdh.local / admin123 · demo@sdh.local / demo1234
      </p>
      <p class="tiny" style="margin-top:8px;text-align:center">${esc(cfg.notice || '')}</p>
    </div>
  </div>`;
  $$('[data-auth]').forEach((b) => b.onclick = () => renderAuth(b.dataset.auth));
  $('#auth-form').onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = { email: fd.get('email'), password: fd.get('password') };
    if (mode === 'register') body.name = fd.get('name');
    try {
      const res = await api('/api/auth/' + mode, { method: 'POST', body: JSON.stringify(body) });
      state.token = res.token; state.user = res.user;
      localStorage.setItem('sdh_token', res.token);
      toast('欢迎，' + res.user.name, 'ok');
      render();
    } catch (err) { toast(err.message, 'err'); }
  };
}

/* ---------------- 布局 ---------------- */
const NAV = [
  { key: 'overview', label: '概览', ic: '◈' },
  { key: 'domains', label: '我的域名', ic: '⌘' },
  { key: 'apply', label: '申请域名', ic: '＋' },
  { key: 'stats', label: '访问统计', ic: '▤' },
  { key: 'keys', label: 'API 密钥', ic: '⚿' },
  { key: 'account', label: '账户设置', ic: '◍' },
];
const ADMIN_NAV = [
  { key: 'admin', label: '后台总览', ic: '▦' },
  { key: 'admin/review', label: '域名审核', ic: '✓' },
  { key: 'admin/domains', label: '全部域名', ic: '☰' },
  { key: 'admin/users', label: '用户管理', ic: '☺' },
  { key: 'admin/orders', label: '订单流水', ic: '￥' },
  { key: 'admin/audit', label: '审计日志', ic: '✎' },
  { key: 'admin/settings', label: '系统设置', ic: '⚙' },
];

function layout(inner, title, sub) {
  const u = state.user;
  const isAdmin = u && u.role === 'admin';
  const cur = state.route.name;
  const navHtml = NAV.map((n) => `<button class="nav-item ${cur === n.key ? 'on' : ''}" data-nav="${n.key}">
      <span class="ic">${n.ic}</span>${n.label}</button>`).join('');
  const adminHtml = isAdmin ? `<div class="nav-sep">管理员</div>` + ADMIN_NAV.map((n) =>
    `<button class="nav-item ${cur === n.key ? 'on' : ''}" data-nav="${n.key}">
      <span class="ic">${n.ic}</span>${n.label}</button>`).join('') : '';
  $('#app').innerHTML = `
  <div class="shell">
    <aside class="side">
      <div class="brand">
        <div class="logo-mark">云</div>
        <div><strong>${esc(state.config?.site_name || '云子域')}</strong><br><small>${esc(state.config?.main_domain || '')}</small></div>
      </div>
      ${navHtml}${adminHtml}
      <div class="side-foot">
        <button class="nav-item" data-nav="logout"><span class="ic">⎋</span>退出登录</button>
      </div>
    </aside>
    <main class="main">
      <div class="topbar">
        <div class="page-title"><h2>${esc(title || '')}</h2>${sub ? `<p>${sub}</p>` : ''}</div>
        <div class="user-chip">
          <div class="avatar">${esc((u?.name || 'U').slice(0, 1))}</div>
          <div><strong class="tiny">${esc(u?.name || '')}</strong><small>${u?.role === 'admin' ? '管理员' : '用户'} · ${money(u?.balance)}</small></div>
        </div>
      </div>
      <div id="view">${inner}</div>
    </main>
  </div>`;
  $$('[data-nav]').forEach((b) => b.onclick = () => {
    const k = b.dataset.nav;
    if (k === 'logout') return logout();
    location.hash = '#/' + k;
  });
}

/* ---------------- 用户概览 ---------------- */
async function viewOverview() {
  const [stats, doms] = await Promise.all([
    api('/api/stats/overview?days=14'),
    api('/api/domains?size=5'),
  ]);
  state.domainsCache = doms.items;
  const cfg = state.config || {};
  const rows = doms.items.map((d) => `
    <tr data-open="${d.id}">
      <td><div class="cell-main mono">${esc(d.fqdn)}</div><div class="cell-sub">${d.purpose === 'dns' ? 'DNS 托管' : '跳转'}</div></td>
      <td>${statusPill(d.status)}</td>
      <td class="mono">${d.hit_count}</td>
      <td>${daysText(d)}</td>
    </tr>`).join('');

  layout(`
    <div class="grid c4">
      <div class="card stat"><div class="label">持有域名</div><div class="val">${stats.domain_total}<small>个</small></div>
        <div class="hint">已激活 ${stats.domain_active} · 待审核 ${stats.domain_pending}</div></div>
      <div class="card stat"><div class="label">今日访问</div><div class="val">${stats.today_hits}<small>次</small></div>
        <div class="hint">累计 ${stats.total_hits} 次</div></div>
      <div class="card stat"><div class="label">账户余额</div><div class="val">${money(state.user.balance)}</div>
        <div class="hint">续费 ${money(cfg.price_per_year)} / 年</div></div>
      <div class="card stat"><div class="label">到期提醒</div><div class="val">${stats.expiring_soon}<small>个</small></div>
        <div class="hint">15 天内到期需续费</div></div>
    </div>
    <div class="grid c2" style="margin-top:14px">
      <div class="card"><h3>近 14 天访问趋势 ${stats.today_hits ? `<span class="pill teal">今日 +${stats.today_hits}</span>` : ''}</h3>${lineChart(stats.series)}</div>
      <div class="card"><h3>热门域名 Top 5</h3>${barList(stats.top_domains, '还没有访问数据，先去创建一个域名吧')}</div>
    </div>
    <div class="card" style="margin-top:14px">
      <h3>最近域名 <a class="btn sm ghost" href="#/domains">全部域名</a></h3>
      ${doms.items.length ? `<div class="table-wrap"><table><thead><tr>
        <th>域名</th><th>状态</th><th>访问</th><th>有效期</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : `<div class="empty"><strong>还没有域名</strong>申请一个专属二级域名，立即开始跳转分发。<br><a class="btn primary" style="margin-top:14px" href="#/apply">去申请</a></div>`}
    </div>
  `, '概览', '你好，' + esc(state.user.name));
  $$('[data-open]').forEach((tr) => tr.onclick = () => openDomain(Number(tr.dataset.open)));
}

/* ---------------- 我的域名 ---------------- */
async function viewDomains(status = 'all', q = '', page = 1) {
  const data = await api(`/api/domains?status=${encodeURIComponent(status)}&q=${encodeURIComponent(q)}&page=${page}&size=20`);
  state.domainsCache = data.items;
  const filters = [['all', '全部'], ['active', '已激活'], ['pending', '待审核'], ['expired', '已过期'], ['suspended', '已停用']];
  const rows = data.items.map((d) => `
    <tr>
      <td onclick="openDomain(${d.id})" style="cursor:pointer">
        <div class="cell-main mono">${esc(d.fqdn)}</div>
        <div class="cell-sub">${esc(d.target_url || (d.purpose === 'dns' ? 'DNS 托管 · ' + d.dns_count + ' 条解析' : '未设置跳转'))}</div>
      </td>
      <td>${statusPill(d.status)}</td>
      <td><span class="pill ${d.purpose === 'dns' ? 'info' : 'teal'}">${d.purpose === 'dns' ? '解析托管' : '跳转分发'}</span></td>
      <td class="mono">${d.hit_count}</td>
      <td class="tiny">${dateOnly(d.expires_at)}<br>${daysText(d)}</td>
      <td><div class="bar">
        <button class="btn sm" onclick="openDomain(${d.id})">管理</button>
        <button class="btn sm ghost" onclick="copyText('${esc(d.fqdn)}')">复制</button>
      </div></td>
    </tr>`).join('');
  const pager = data.total > 20 ? `<div class="bar" style="margin-top:12px">
      <button class="btn sm" ${page <= 1 ? 'disabled' : ''} onclick="gotoDomains(${page - 1})">上一页</button>
      <span class="muted tiny">第 ${page} / ${Math.ceil(data.total / 20)} 页 · 共 ${data.total} 条</span>
      <button class="btn sm" ${page >= Math.ceil(data.total / 20) ? 'disabled' : ''} onclick="gotoDomains(${page + 1})">下一页</button>
    </div>` : '';

  layout(`
    <div class="card">
      <div class="bar" style="margin-bottom:14px">
        <div class="bar">${filters.map(([k, l]) => `<button class="btn sm ${status === k ? 'primary' : ''}" data-status="${k}">${l}</button>`).join('')}</div>
        <div class="spacer"></div>
        <input class="input" id="q" placeholder="搜索域名 / 跳转地址" style="max-width:230px" value="${esc(q)}">
        <a class="btn primary" href="#/apply">＋ 申请新域名</a>
      </div>
      ${data.items.length ? `<div class="table-wrap"><table><thead><tr>
        <th>域名 / 用途</th><th>状态</th><th>类型</th><th>访问</th><th>有效期</th><th>操作</th>
      </tr></thead><tbody>${rows}</tbody></table></div>${pager}`
      : `<div class="empty"><strong>没有符合条件的域名</strong>换个筛选条件，或申请一个新域名。<br><a class="btn primary" style="margin-top:14px" href="#/apply">去申请</a></div>`}
    </div>
    <div class="card" style="margin-top:14px">
      <h3>域名分发说明</h3>
      <div class="tiny muted" style="line-height:1.9">
        1. 申请通过后，域名即刻生效：<code>https://{前缀}.${esc(state.config.main_domain)}</code><br>
        2. <b>跳转分发</b>：访问该二级域名会 301/302 跳转到你设置的目标地址，可用于活动页、短链、渠道分发；<br>
        3. <b>解析托管</b>：可为域名配置 A / CNAME / TXT / MX 记录，支持同步至 Cloudflare 或阿里云 DNS；<br>
        4. 到期前 15 天请及时续费，逾期域名自动停用（访问将提示已到期）。
      </div>
    </div>
  `, '我的域名', `共 ${data.total} 个域名`);
  $$('[data-status]').forEach((b) => b.onclick = () => location.hash = `#/domains/${b.dataset.status}`);
  $('#q').onkeydown = (e) => { if (e.key === 'Enter') location.hash = `#/domains/${status}?q=${encodeURIComponent(e.target.value)}`; };
}

window.gotoDomains = (p) => {
  const cur = state.route;
  location.hash = `#/domains/${cur.params[0] || 'all'}?page=${p}`;
};

window.copyText = async (text) => {
  try {
    await navigator.clipboard.writeText(text);
    toast('已复制：' + text, 'ok');
  } catch (e) {
    const ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); ta.remove();
    toast('已复制：' + text, 'ok');
  }
};

/* ---------------- 申请域名 ---------------- */
function viewApply() {
  const md = state.config.main_domain;
  layout(`
    <div class="grid c2">
      <div class="card">
        <h3>申请二级域名</h3>
        <div class="field">
          <label>域名前缀</label>
          <div class="bar" style="gap:0;flex-wrap:nowrap">
            <input class="input" id="prefix" placeholder="例如 promo" maxlength="32"
                   style="width:auto;flex:1;min-width:0;border-top-right-radius:0;border-bottom-right-radius:0">
            <span class="btn" style="border-radius:0 10px 10px 0;border-left:0;background:#f8fafc;white-space:nowrap">.${esc(md)}</span>
          </div>
          <div id="prefix-msg" class="tiny muted" style="margin-top:6px">3-32 位小写字母/数字/连字符，不能是保留词</div>
        </div>
        <div class="grid c2" style="gap:10px">
          <div class="field"><label>用途</label>
            <select class="input" id="purpose">
              <option value="redirect">跳转分发（推荐）</option>
              <option value="dns">DNS 解析托管</option>
            </select>
          </div>
          <div class="field"><label>跳转方式</label>
            <select class="input" id="rtype">
              <option value="302">302 临时跳转</option>
              <option value="301">301 永久跳转</option>
            </select>
          </div>
        </div>
        <div class="field" id="target-field"><label>跳转目标地址</label>
          <input class="input" id="target" placeholder="https://你的落地页">
        </div>
        <div class="field"><label>备注（可选）</label>
          <input class="input" id="note" placeholder="例如：双十一活动页">
        </div>
        <button class="btn primary block" id="submit-apply">提交申请</button>
        <p class="tiny muted" style="margin-top:12px">
          ${state.config.auto_approve ? '当前为自动审核，提交后立即生效。' : '提交后需管理员审核，通常 1 个工作日内完成。'}
        </p>
      </div>
      <div class="card">
        <h3>可分配示例</h3>
        <div class="tiny muted" style="line-height:2">
          每个账号最多同时持有 <b>${esc(String(state.config.max_domains_per_user))}</b> 个域名，每年 <b>${money(state.config.price_per_year)}</b>。
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:12px">
          ${['promo', 'go', 'sale', 'vip', 'app'].map((p) => `<span class="pill teal mono" style="cursor:pointer" onclick="document.getElementById('prefix').value='${p}';checkPrefix()">${p}.${esc(md)}</span>`).join('')}
        </div>
        <hr style="border:0;border-top:1px solid var(--line);margin:16px 0">
        <h3>解析托管如何工作</h3>
        <div class="tiny muted" style="line-height:1.9">
          选择「DNS 解析托管」后，可在域名详情中添加 A / CNAME / TXT / MX 记录。<br>
          若管理员配置了 Cloudflare 或阿里云 DNS 凭据，记录会实时同步到真实 DNS；否则为本地托管记录，仅供展示与预配置。
        </div>
      </div>
    </div>
  `, '申请域名', '前缀一经审核不可修改，请谨慎选择');

  const prefixEl = $('#prefix');
  const msgEl = $('#prefix-msg');
  let timer = null;
  window.checkPrefix = async () => {
    const v = prefixEl.value.trim().toLowerCase();
    if (!v) { msgEl.className = 'tiny muted'; msgEl.textContent = '3-32 位小写字母/数字/连字符，不能是保留词'; return; }
    try {
      const r = await api('/api/domains/check?prefix=' + encodeURIComponent(v));
      if (r.available) {
        msgEl.className = 'tiny'; msgEl.style.color = 'var(--ok)';
        msgEl.innerHTML = `✓ <b class="mono">${esc(r.fqdn)}</b> 可以使用`;
      } else {
        msgEl.className = 'tiny'; msgEl.style.color = 'var(--danger)';
        msgEl.textContent = '✗ ' + r.reason;
      }
    } catch (e) { msgEl.textContent = e.message; }
  };
  prefixEl.oninput = () => { clearTimeout(timer); timer = setTimeout(window.checkPrefix, 320); };
  $('#purpose').onchange = (e) => {
    $('#target-field').style.display = e.target.value === 'dns' ? 'none' : 'block';
  };
  $('#submit-apply').onclick = async () => {
    const body = {
      prefix: prefixEl.value.trim().toLowerCase(),
      purpose: $('#purpose').value,
      target_url: $('#target').value.trim(),
      redirect_type: Number($('#rtype').value),
      note: $('#note').value.trim(),
    };
    if (body.purpose === 'redirect' && !body.target_url && !confirm('未填写跳转地址，域名激活后访问将显示"尚未配置跳转"。继续提交？')) return;
    const btn = $('#submit-apply');
    btn.disabled = true; btn.textContent = '提交中…';
    try {
      const d = await api('/api/domains', { method: 'POST', body: JSON.stringify(body) });
      toast(d.status === 'active' ? '申请成功，域名已激活' : '已提交，等待审核', 'ok');
      location.hash = '#/domains';
    } catch (e) { toast(e.message, 'err'); btn.disabled = false; btn.textContent = '提交申请'; }
  };
}

/* ---------------- 域名详情弹窗 ---------------- */
window.openDomain = async (id) => {
  let d, stats;
  try {
    [d, stats] = await Promise.all([api('/api/domains/' + id), api(`/api/domains/${id}/stats?days=14`)]);
  } catch (e) { return toast(e.message, 'err'); }
  const mask = document.createElement('div');
  mask.className = 'modal-mask';
  const md = state.config.main_domain;
  const tabBtn = (k, l) => `<button class="btn sm ${k === 'info' ? 'primary' : ''}" data-tab="${k}">${l}</button>`;
  mask.innerHTML = `
    <div class="modal drawer">
      <div class="modal-head">
        <div><h3 class="mono">${esc(d.fqdn)}</h3>
          <div class="tiny muted" style="margin-top:4px">${esc((d.note || '无备注'))} · 创建于 ${fmt(d.created_at)}</div></div>
        <button class="icon-btn" id="close-modal">✕</button>
      </div>
      <div class="grid c3" style="margin-bottom:14px">
        <div class="card stat" style="padding:12px"><div class="label">状态</div><div style="margin-top:6px">${statusPill(d.status)}</div></div>
        <div class="card stat" style="padding:12px"><div class="label">访问次数</div><div class="val" style="font-size:20px">${d.hit_count}</div></div>
        <div class="card stat" style="padding:12px"><div class="label">有效期</div><div class="val" style="font-size:15px;margin-top:10px">${dateOnly(d.expires_at)}</div>${daysText(d)}</div>
      </div>
      <div class="bar" style="margin-bottom:14px">
        ${tabBtn('info', '配置')}${tabBtn('stats', '访问统计')}${tabBtn('dns', '解析记录')}
        <div class="spacer"></div>
        <button class="btn sm ghost" onclick="copyText('https://${esc(d.fqdn)}')">复制链接</button>
      </div>
      <div id="tab-body"></div>
    </div>`;
  document.body.appendChild(mask);
  const close = () => mask.remove();
  $('#close-modal', mask).onclick = close;
  mask.addEventListener('click', (e) => { if (e.target === mask) close(); });

  const body = $('#tab-body', mask);
  const switchTab = (k) => {
    $$('[data-tab]', mask).forEach((b) => b.classList.toggle('primary', b.dataset.tab === k));
    if (k === 'info') renderInfoTab();
    if (k === 'stats') renderStatsTab();
    if (k === 'dns') renderDnsTab();
  };
  $$('[data-tab]', mask).forEach((b) => b.onclick = () => switchTab(b.dataset.tab));

  function renderInfoTab() {
    const isRedirect = d.purpose === 'redirect';
    body.innerHTML = `
      <div class="grid c2" style="gap:14px">
        <div>
          <div class="field"><label>用途</label>
            <select class="input" id="f-purpose">
              <option value="redirect" ${isRedirect ? 'selected' : ''}>跳转分发</option>
              <option value="dns" ${!isRedirect ? 'selected' : ''}>DNS 解析托管</option>
            </select></div>
          <div class="field" id="f-target-wrap" style="${isRedirect ? '' : 'display:none'}">
            <label>跳转目标地址</label>
            <input class="input" id="f-target" value="${esc(d.target_url || '')}" placeholder="https://目标页面">
          </div>
          <div class="field" id="f-rtype-wrap" style="${isRedirect ? '' : 'display:none'}"><label>跳转方式</label>
            <select class="input" id="f-rtype">
              <option value="302" ${d.redirect_type === 302 ? 'selected' : ''}>302 临时</option>
              <option value="301" ${d.redirect_type === 301 ? 'selected' : ''}>301 永久</option>
            </select></div>
          <div class="field"><label>备注</label>
            <input class="input" id="f-note" value="${esc(d.note || '')}"></div>
          <div class="bar">
            <button class="btn primary" id="save-info">保存修改</button>
            <button class="btn" id="renew-btn">续费</button>
          </div>
        </div>
        <div>
          <div class="card" style="padding:14px">
            <div class="tiny muted">访问地址</div>
            <div class="mono" style="margin:6px 0 12px;word-break:break-all">https://${esc(d.fqdn)}</div>
            <div class="tiny muted">本地测试（未配置通配 DNS 时）</div>
            <div class="mono" style="margin:6px 0 12px">http://127.0.0.1:8000/t/${esc(d.prefix)}</div>
            <div class="tiny muted">创建 / 激活</div>
            <div class="tiny" style="margin-top:4px">${fmt(d.created_at)} / ${fmt(d.activated_at)}</div>
          </div>
          <button class="btn danger block" style="margin-top:12px" id="del-btn">删除该域名</button>
        </div>
      </div>`;
    $('#f-purpose', body).onchange = (e) => {
      const r = e.target.value === 'redirect';
      $('#f-target-wrap', body).style.display = r ? 'block' : 'none';
      $('#f-rtype-wrap', body).style.display = r ? 'block' : 'none';
    };
    $('#save-info', body).onclick = async () => {
      try {
        const updated = await api('/api/domains/' + d.id, {
          method: 'PATCH', body: JSON.stringify({
            purpose: $('#f-purpose', body).value,
            target_url: $('#f-target', body).value.trim(),
            redirect_type: Number($('#f-rtype', body).value),
            note: $('#f-note', body).value.trim(),
          }),
        });
        d = updated; toast('已保存', 'ok'); renderInfoTab();
      } catch (e) { toast(e.message, 'err'); }
    };
    $('#renew-btn', body).onclick = () => renewDialog(d, (nd) => { d = nd; switchTab('info'); });
    $('#del-btn', body).onclick = async () => {
      if (!confirm(`确定删除 ${d.fqdn}？删除后不可恢复，解析记录一并清除。`)) return;
      try { await api('/api/domains/' + d.id, { method: 'DELETE' }); toast('已删除', 'ok'); close(); route(); }
      catch (e) { toast(e.message, 'err'); }
    };
  }

  function renderStatsTab() {
    body.innerHTML = `
      <div class="bar" style="margin-bottom:10px">
        <span class="muted tiny">最近 14 天</span><div class="spacer"></div>
        <button class="btn sm" id="load-visits">刷新访问明细</button>
      </div>
      ${lineChart(stats.series)}
      <div class="grid c3" style="margin-top:12px">
        <div><h3 style="font-size:13px">设备分布</h3>${barList(stats.devices)}</div>
        <div><h3 style="font-size:13px">来源 Referer</h3>${barList(stats.referers)}</div>
        <div><h3 style="font-size:13px">地区</h3>${barList(stats.countries, '暂无地区数据')}</div>
      </div>
      <div id="visit-list" style="margin-top:14px"></div>`;
    $('#load-visits', body).onclick = async () => {
      try {
        const v = await api(`/api/domains/${d.id}/visits?limit=30`);
        $('#visit-list', body).innerHTML = v.items.length ? `<div class="table-wrap"><table>
          <thead><tr><th>时间</th><th>IP</th><th>设备</th><th>来源</th><th>路径</th></tr></thead><tbody>
          ${v.items.map((x) => `<tr><td class="mono tiny">${fmt(x.ts)}</td><td class="mono tiny">${esc(x.ip || '—')}</td>
            <td>${esc(x.device)}</td><td class="tiny">${esc((x.referer || '直接访问').slice(0, 30))}</td>
            <td class="mono tiny">${esc(x.path || '/')}</td></tr>`).join('')}
          </tbody></table></div>` : '<div class="empty tiny">暂无访问明细</div>';
      } catch (e) { toast(e.message, 'err'); }
    };
  }

  async function renderDnsTab() {
    if (d.purpose !== 'dns') {
      body.innerHTML = `<div class="empty"><strong>当前用途为「跳转分发」</strong>如需配置解析记录，请先在「配置」中把用途切换为 DNS 解析托管。</div>`;
      return;
    }
    let data;
    try { data = await api(`/api/domains/${d.id}/dns`); } catch (e) { return toast(e.message, 'err'); }
    const prov = (data.providers || []).find((p) => p.current) || { label: '本地托管' };
    const rows = data.items.map((r) => `
      <tr>
        <td><span class="pill ${r.type === 'A' ? 'teal' : 'info'}">${esc(r.type)}</span></td>
        <td class="mono">${esc(r.name)}</td>
        <td class="mono" style="word-break:break-all">${esc(r.value)}</td>
        <td class="mono tiny">${r.ttl}s</td>
        <td>${syncPill(r.sync_status)}<div class="cell-sub">${esc((r.sync_message || '').slice(0, 26))}</div></td>
        <td><div class="bar">
          ${r.sync_status === 'failed' ? `<button class="btn sm" data-sync="${r.id}">重试同步</button>` : ''}
          <button class="btn sm danger" data-delrec="${r.id}">删除</button>
        </div></td>
      </tr>`).join('');
    body.innerHTML = `
      <div class="bar" style="margin-bottom:10px">
        <span class="pill teal">当前服务商：${esc(prov.label)}</span>
        <span class="pill ${prov.key === 'manual' ? '' : 'ok'}">${prov.key === 'manual' ? '本地托管（不写入真实 DNS）' : '已连接'}</span>
        <div class="spacer"></div>
        <button class="btn sm primary" id="add-rec">＋ 添加记录</button>
      </div>
      ${data.items.length ? `<div class="table-wrap"><table>
        <thead><tr><th>类型</th><th>主机</th><th>值</th><th>TTL</th><th>同步状态</th><th>操作</th></tr></thead>
        <tbody>${rows}</tbody></table></div>` : `<div class="empty"><strong>暂无解析记录</strong>添加 A 记录指向服务器 IP，或用 CNAME 指向 CDN。</div>`}
      <div id="rec-form"></div>`;
    $('#add-rec', body).onclick = () => recordForm(null);
    $$('[data-delrec]', body).forEach((b) => b.onclick = async () => {
      if (!confirm('删除该解析记录？' + (prov.key !== 'manual' ? ' 也会尝试删除远程记录。' : ''))) return;
      try { await api(`/api/domains/${d.id}/dns/${b.dataset.delrec}`, { method: 'DELETE' }); toast('已删除', 'ok'); renderDnsTab(); }
      catch (e) { toast(e.message, 'err'); }
    });
    $$('[data-sync]', body).forEach((b) => b.onclick = async () => {
      try {
        const r = await api(`/api/domains/${d.id}/dns/${b.dataset.sync}/sync`, { method: 'POST' });
        toast(r.message, 'ok'); renderDnsTab();
      } catch (e) { toast(e.message, 'err'); renderDnsTab(); }
    });

    function recordForm() {
      const box = $('#rec-form', body);
      box.innerHTML = `
        <div class="card" style="margin-top:14px;background:#f8fafc">
          <div class="grid c4" style="gap:10px">
            <div class="field"><label>类型</label><select class="input" id="rt">
              <option>A</option><option>CNAME</option><option>TXT</option><option>AAAA</option><option>MX</option></select></div>
            <div class="field"><label>主机记录</label><input class="input" id="rn" value="@" placeholder="@ 或 www"></div>
            <div class="field" style="grid-column:span 2"><label>记录值</label>
              <input class="input" id="rv" placeholder="1.2.3.4 或 cdn.example.net"></div>
          </div>
          <div class="grid c3" style="gap:10px">
            <div class="field"><label>TTL（秒）</label><input class="input" id="rtl" type="number" value="600"></div>
            <div class="field"><label>优先级（MX）</label><input class="input" id="rp" type="number" value="10"></div>
            <div class="field"><label>Cloudflare 代理</label>
              <select class="input" id="rprox"><option value="0">关闭</option><option value="1">开启</option></select></div>
          </div>
          <div class="bar"><button class="btn primary" id="save-rec">保存记录</button>
            <button class="btn ghost" id="cancel-rec">取消</button></div>
        </div>`;
      $('#cancel-rec', box).onclick = () => box.innerHTML = '';
      $('#save-rec', box).onclick = async () => {
        try {
          const res = await api(`/api/domains/${d.id}/dns`, {
            method: 'POST', body: JSON.stringify({
              type: $('#rt', box).value, name: $('#rn', box).value.trim() || '@',
              value: $('#rv', box).value.trim(), ttl: Number($('#rtl', box).value) || 600,
              priority: Number($('#rp', box).value) || 10, proxied: $('#rprox', box).value === '1',
            }),
          });
          toast(res.message || '已添加', res.record.sync_status === 'failed' ? 'err' : 'ok');
          renderDnsTab();
        } catch (e) { toast(e.message, 'err'); }
      };
    }
  }

  const syncPill = (s) => ({
    synced: '<span class="pill ok">已同步</span>',
    pending: '<span class="pill warn">待同步</span>',
    failed: '<span class="pill danger">同步失败</span>',
    manual: '<span class="pill">本地</span>',
  }[s] || `<span class="pill">${esc(s)}</span>`);

  switchTab('info');
};

/* ---------------- 续费弹窗 ---------------- */
window.renewDialog = (d, done) => {
  const price = Number(state.config.price_per_year || 0);
  const mask = document.createElement('div');
  mask.className = 'modal-mask';
  mask.innerHTML = `
    <div class="modal" style="max-width:400px">
      <div class="modal-head"><h3>续费 ${esc(d.fqdn)}</h3><button class="icon-btn" id="rx">✕</button></div>
      <div class="field"><label>续费年限</label>
        <select class="input" id="ry">${[1, 2, 3, 5].map((n) => `<option value="${n}">${n} 年（${money(price * n)}）</option>`).join('')}</select></div>
      <div class="tiny muted" style="margin-bottom:12px">当前余额 ${money(state.user.balance)} · 从余额中扣款</div>
      <button class="btn primary block" id="do-renew">确认续费</button>
    </div>`;
  document.body.appendChild(mask);
  const close = () => mask.remove();
  $('#rx', mask).onclick = close;
  $('#do-renew', mask).onclick = async () => {
    try {
      const r = await api(`/api/domains/${d.id}/renew`, {
        method: 'POST',
        body: JSON.stringify({ years: Number($('#ry', mask).value), pay_with_balance: true }),
      });
      state.user.balance = r.balance;
      toast(`续费成功，已延长 ${r.years} 年，扣款 ${money(r.amount)}`, 'ok');
      close(); done && done(r.domain); route();
    } catch (e) { toast(e.message, 'err'); }
  };
};

/* ---------------- 全局访问统计 ---------------- */
async function viewStats() {
  const days = 30;
  const data = await api(`/api/stats/overview?days=${days}`);
  const rows = data.top_domains.map((t) => `
    <tr><td class="mono">${esc(t.name)}</td><td class="mono">${t.count}</td>
      <td><div class="mini-bar-track" style="width:100%"><div class="mini-bar-fill" style="width:${Math.round(t.count / (data.top_domains[0]?.count || 1) * 100)}%"></div></div></td></tr>`).join('');
  layout(`
    <div class="grid c4">
      <div class="card stat"><div class="label">今日访问</div><div class="val">${data.today_hits}</div><div class="hint">近 ${days} 天 ${data.period_hits} 次</div></div>
      <div class="card stat"><div class="label">累计访问</div><div class="val">${data.total_hits}</div><div class="hint">所有域名合计</div></div>
      <div class="card stat"><div class="label">活跃域名</div><div class="val">${data.domain_active}<small>个</small></div><div class="hint">共 ${data.domain_total} 个</div></div>
      <div class="card stat"><div class="label">到期提醒</div><div class="val">${data.expiring_soon}<small>个</small></div><div class="hint">15 天内到期</div></div>
    </div>
    <div class="card" style="margin-top:14px"><h3>近 ${days} 天访问趋势</h3>${lineChart(data.series)}</div>
    <div class="grid c3" style="margin-top:14px">
      <div class="card"><h3>热门域名</h3>${data.top_domains.length ? `<div class="table-wrap"><table style="min-width:auto"><tbody>${rows}</tbody></table></div>` : '<div class="empty tiny">暂无数据</div>'}</div>
      <div class="card"><h3>设备分布</h3>${barList(data.devices)}</div>
      <div class="card"><h3>来源渠道</h3>${barList(data.referers)}</div>
    </div>
  `, '访问统计', '汇总你名下所有域名的访问表现');
}

/* ---------------- API 密钥 ---------------- */
async function viewKeys() {
  const data = await api('/api/keys');
  const rows = data.items.map((k) => `
    <tr><td><div class="cell-main">${esc(k.name)}</div><div class="cell-sub mono">${esc(k.key_masked)}</div></td>
      <td>${k.status === 'active' ? '<span class="pill ok">启用</span>' : '<span class="pill danger">停用</span>'}</td>
      <td class="tiny">${fmt(k.last_used_at)}</td>
      <td><button class="btn sm danger" data-delkey="${k.id}">删除</button></td></tr>`).join('');
  layout(`
    <div class="card">
      <div class="bar" style="margin-bottom:14px">
        <div><h3>API 密钥</h3><div class="tiny muted">用于通过开放 API 自动化创建域名、修改跳转、拉取统计</div></div>
        <div class="spacer"></div><button class="btn primary" id="new-key">＋ 创建密钥</button>
      </div>
      ${data.items.length ? `<div class="table-wrap"><table><thead><tr><th>名称 / 密钥</th><th>状态</th><th>最近使用</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : '<div class="empty"><strong>暂无 API 密钥</strong>创建后可调用 /api/v1 接口。</div>'}
    </div>
    <div class="card" style="margin-top:14px"><h3>接口示例</h3>
      <pre class="mono tiny" style="background:#f8fafc;padding:14px;border-radius:10px;overflow:auto;line-height:1.7;margin:0">
# 查询我的域名
curl -H "X-API-Key: sdh_xxx" ${location.origin}/api/v1/domains

# 创建跳转域名
curl -X POST ${location.origin}/api/v1/domains \\
  -H "X-API-Key: sdh_xxx" -H "Content-Type: application/json" \\
  -d '{"prefix":"promo","target_url":"https://example.com/landing"}'

# 修改跳转目标
curl -X PATCH ${location.origin}/api/v1/domains/12 \\
  -H "X-API-Key: sdh_xxx" -H "Content-Type: application/json" \\
  -d '{"target_url":"https://example.com/new"}'

# 拉取统计
curl -H "X-API-Key: sdh_xxx" "${location.origin}/api/v1/domains/12/stats?days=30"</pre>
    </div>
  `, 'API 密钥', '密钥仅在创建时完整展示一次');
  $('#new-key').onclick = () => {
    const mask = document.createElement('div');
    mask.className = 'modal-mask';
    mask.innerHTML = `<div class="modal" style="max-width:400px">
      <div class="modal-head"><h3>创建 API 密钥</h3><button class="icon-btn" id="kx">✕</button></div>
      <div class="field"><label>名称</label><input class="input" id="kn" placeholder="例如 CI 部署脚本"></div>
      <button class="btn primary block" id="kc">创建</button></div>`;
    document.body.appendChild(mask);
    $('#kx', mask).onclick = () => mask.remove();
    $('#kc', mask).onclick = async () => {
      try {
        const r = await api('/api/keys', { method: 'POST', body: JSON.stringify({ name: $('#kn', mask).value.trim() || '未命名密钥' }) });
        mask.remove();
        const m2 = document.createElement('div');
        m2.className = 'modal-mask';
        m2.innerHTML = `<div class="modal" style="max-width:460px">
          <div class="modal-head"><h3>密钥创建成功</h3><button class="icon-btn" id="cx">✕</button></div>
          <div class="card mono tiny" style="word-break:break-all;background:#f8fafc" id="thekey">${esc(r.key)}</div>
          <p class="tiny" style="color:var(--danger)">请立即复制保存，关闭后不再完整展示。</p>
          <button class="btn primary block" id="copykey">复制密钥</button></div>`;
        document.body.appendChild(m2);
        $('#cx', m2).onclick = () => { m2.remove(); viewKeys(); };
        $('#copykey', m2).onclick = () => copyText(r.key);
      } catch (e) { toast(e.message, 'err'); }
    };
  };
  $$('[data-delkey]').forEach((b) => b.onclick = async () => {
    if (!confirm('删除该密钥？使用它的脚本将立即失效。')) return;
    try { await api('/api/keys/' + b.dataset.delkey, { method: 'DELETE' }); toast('已删除', 'ok'); viewKeys(); }
    catch (e) { toast(e.message, 'err'); }
  });
}

/* ---------------- 账户 ---------------- */
function viewAccount() {
  layout(`
    <div class="grid c2">
      <div class="card"><h3>账户信息</h3>
        <div class="field"><label>昵称</label><input class="input" value="${esc(state.user.name)}" disabled></div>
        <div class="field"><label>邮箱</label><input class="input" value="${esc(state.user.email)}" disabled></div>
        <div class="field"><label>角色 / 注册时间</label><input class="input" value="${state.user.role === 'admin' ? '管理员' : '普通用户'} · ${fmt(state.user.created_at)}" disabled></div>
      </div>
      <div>
        <div class="card stat"><div class="label">账户余额</div><div class="val">${money(state.user.balance)}</div>
          <div class="hint">用于域名续费（${money(state.config.price_per_year)} / 年）</div>
          <div class="bar" style="margin-top:12px">
            ${[50, 100, 200].map((n) => `<button class="btn sm" data-rc="${n}">充值 ${n} 元</button>`).join('')}
          </div>
          <div class="tiny muted" style="margin-top:8px">演示环境为模拟充值，生产环境应接入支付回调。</div>
        </div>
        <div class="card" style="margin-top:14px"><h3>修改密码</h3>
          <div class="field"><label>原密码</label><input class="input" type="password" id="old-pw"></div>
          <div class="field"><label>新密码</label><input class="input" type="password" id="new-pw" placeholder="至少 6 位"></div>
          <button class="btn primary" id="chpw">保存新密码</button>
        </div>
      </div>
    </div>
  `, '账户设置', '余额、密码与个人信息');
  $$('[data-rc]').forEach((b) => b.onclick = async () => {
    try {
      const r = await api('/api/auth/recharge', { method: 'POST', body: JSON.stringify({ amount: Number(b.dataset.rc) }) });
      state.user.balance = r.balance; toast('充值成功（模拟）', 'ok'); route();
    } catch (e) { toast(e.message, 'err'); }
  });
  $('#chpw').onclick = async () => {
    try {
      await api('/api/auth/password', { method: 'POST', body: JSON.stringify({
        old_password: $('#old-pw').value, new_password: $('#new-pw').value }) });
      toast('密码已更新', 'ok'); $('#old-pw').value = ''; $('#new-pw').value = '';
    } catch (e) { toast(e.message, 'err'); }
  };
}

/* ---------------- 路由 ---------------- */
function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [pathPart, queryPart] = raw.split('?');
  const parts = pathPart.split('/').filter(Boolean);
  const query = { page: 1, q: '', status: 'all' };
  if (queryPart) {
    new URLSearchParams(queryPart).forEach((v, k) => query[k] = v);
  }
  let name = 'overview';
  const params = [];
  if (parts[0] === 'admin') { name = 'admin'; params.push(parts[1] || 'overview'); }
  else if (parts.length) { name = parts[0]; params.push(...parts.slice(1)); }
  state.route = { name, params, query };
}

async function route() {
  parseHash();
  const { name, params, query } = state.route;
  try {
    if (name === 'overview') await viewOverview();
    else if (name === 'domains') await viewDomains(params[0] || query.status || 'all', query.q || '', Number(query.page || 1));
    else if (name === 'apply') viewApply();
    else if (name === 'stats') await viewStats();
    else if (name === 'keys') await viewKeys();
    else if (name === 'account') viewAccount();
    else if (name === 'admin') await viewAdmin(params[0] || 'overview');
    else await viewOverview();
  } catch (e) {
    if (e.status === 401) { state.token = ''; localStorage.removeItem('sdh_token'); return render(); }
    toast(e.message || '加载失败', 'err');
    layout(`<div class="empty"><strong>加载失败</strong>${esc(e.message || '')}</div>`, '出错了');
  }
}

async function render() {
  try {
    state.config = await api('/api/auth/public-config');
  } catch (e) { state.config = {}; }
  if (!state.token) {
    state.user = null; renderAuth(); return;
  }
  try {
    state.user = await api('/api/auth/me');
  } catch (e) {
    localStorage.removeItem('sdh_token'); state.token = ''; renderAuth(); return;
  }
  await route();
}

window.addEventListener('hashchange', () => { if (state.user) route(); });
render();

/* ---------------- 管理后台 ---------------- */
async function viewAdmin(sub) {
  if (!state.user || state.user.role !== 'admin') {
    return layout('<div class="empty"><strong>需要管理员权限</strong>请用管理员账号登录。</div>', '无权访问');
  }
  if (sub === 'overview') return adminOverview();
  if (sub === 'review') return adminReview();
  if (sub === 'domains') return adminDomains();
  if (sub === 'users') return adminUsers();
  if (sub === 'orders') return adminOrders();
  if (sub === 'audit') return adminAudit();
  if (sub === 'settings') return adminSettings();
  return adminOverview();
}

async function adminOverview() {
  const d = await api('/api/admin/overview');
  const pend = d.recent_domains.filter((x) => x.status === 'pending');
  const rows = d.recent_domains.map((x) => `
    <tr><td class="mono">${esc(x.fqdn)}</td><td>${statusPill(x.status)}</td>
      <td class="mono">${x.hit_count}</td><td class="tiny">${fmt(x.created_at)}</td></tr>`).join('');
  layout(`
    <div class="grid c4">
      <div class="card stat"><div class="label">用户总数</div><div class="val">${d.users}</div><div class="hint">今日新增 ${d.users_today}</div></div>
      <div class="card stat"><div class="label">域名总数</div><div class="val">${d.domains}</div><div class="hint">激活 ${d.active} · 过期 ${d.expired}</div></div>
      <div class="card stat"><div class="label">待审核</div><div class="val" style="color:var(--warn)">${d.pending}</div>
        <div class="hint"><a href="#/admin/review">立即处理 →</a></div></div>
      <div class="card stat"><div class="label">累计收入</div><div class="val">${money(d.revenue)}</div><div class="hint">今日访问 ${d.hits_today} 次</div></div>
    </div>
    <div class="grid c2" style="margin-top:14px">
      <div class="card"><h3>全站访问趋势（14 天）</h3>${lineChart(d.visit_series)}
        <div class="tiny muted" style="margin-top:8px">累计访问 ${d.hits_total} 次</div></div>
      <div class="card"><h3>待审核队列 ${d.pending ? `<span class="pill warn">${d.pending}</span>` : ''}</h3>
        ${pend.length ? pend.map((x) => `<div class="bar" style="padding:8px 0;border-bottom:1px solid #f1f5f9">
          <span class="mono">${esc(x.fqdn)}</span><span class="pill info">${x.purpose === 'dns' ? '托管' : '跳转'}</span>
          <div class="spacer"></div>
          <button class="btn sm primary" data-ap="${x.id}">通过</button>
          <button class="btn sm danger" data-rj="${x.id}">拒绝</button></div>`).join('')
          : '<div class="empty tiny">没有待审核申请 🎉</div>'}
        <div style="margin-top:12px"><a class="btn sm ghost" href="#/admin/review">查看完整队列</a></div>
      </div>
    </div>
    <div class="card" style="margin-top:14px"><h3>最近提交的域名</h3>
      <div class="table-wrap"><table><thead><tr><th>域名</th><th>状态</th><th>访问</th><th>提交时间</th></tr></thead>
        <tbody>${rows}</tbody></table></div></div>
    <div class="card" style="margin-top:14px"><h3>DNS 服务商状态</h3>
      <div class="bar">${d.providers.map((p) => `<span class="pill ${p.current ? 'ok' : ''}">${esc(p.label)}${p.configured ? '' : '（未配置）'}${p.current ? ' · 使用中' : ''}</span>`).join('')}</div>
    </div>
  `, '后台总览', '全站运营数据一览');
  $$('[data-ap]').forEach((b) => b.onclick = () => adminApprove(b.dataset.ap));
  $$('[data-rj]').forEach((b) => b.onclick = () => adminReject(b.dataset.rj));
}

async function adminApprove(id) {
  try { await api(`/api/admin/domains/${id}/approve`, { method: 'POST' }); toast('已通过', 'ok'); route(); }
  catch (e) { toast(e.message, 'err'); }
}

async function adminReject(id) {
  const reason = prompt('拒绝原因（会展示给用户）', '资料不完整，请补充用途说明');
  if (!reason) return;
  try { await api(`/api/admin/domains/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }); toast('已拒绝', 'ok'); route(); }
  catch (e) { toast(e.message, 'err'); }
}

async function adminReview() {
  const d = await api('/api/admin/domains?status=pending&size=50');
  const rows = d.items.map((x) => `
    <tr><td><input type="checkbox" class="pick" value="${x.id}" style="width:16px;height:16px"></td>
      <td><div class="cell-main mono">${esc(x.fqdn)}</div><div class="cell-sub">${esc(x.note || '无备注')}</div></td>
      <td class="tiny">${esc(x.owner_email)}<br>${esc(x.owner_name)}</td>
      <td><span class="pill ${x.purpose === 'dns' ? 'info' : 'teal'}">${x.purpose === 'dns' ? '解析托管' : '跳转'}</span>
        ${x.target_url ? `<div class="cell-sub" style="max-width:180px;word-break:break-all">${esc(x.target_url)}</div>` : ''}</td>
      <td class="tiny">${fmt(x.created_at)}</td>
      <td><div class="bar"><button class="btn sm primary" data-ap="${x.id}">通过</button>
        <button class="btn sm danger" data-rj="${x.id}">拒绝</button></div></td></tr>`).join('');
  layout(`
    <div class="card">
      <div class="bar" style="margin-bottom:14px">
        <h3 style="margin:0">待审核申请（${d.total}）</h3><div class="spacer"></div>
        <button class="btn sm" id="pick-all">全选</button>
        <button class="btn sm primary" id="bulk-ok" ${d.items.length ? '' : 'disabled'}>批量通过</button>
        <button class="btn sm danger" id="bulk-rj" ${d.items.length ? '' : 'disabled'}>批量拒绝</button>
      </div>
      ${d.items.length ? `<div class="table-wrap"><table><thead><tr>
        <th style="width:36px"></th><th>域名 / 备注</th><th>申请人</th><th>用途</th><th>提交时间</th><th>操作</th>
      </tr></thead><tbody>${rows}</tbody></table></div>`
      : '<div class="empty"><strong>队列已清空</strong>所有申请都已处理完毕。</div>'}
    </div>
  `, '域名审核', '审核用户提交的域名申请');
  $$('[data-ap]').forEach((b) => b.onclick = () => adminApprove(b.dataset.ap));
  $$('[data-rj]').forEach((b) => b.onclick = () => adminReject(b.dataset.rj));
  $('#pick-all').onclick = () => {
    const boxes = $$('.pick'); const on = boxes.some((b) => !b.checked);
    boxes.forEach((b) => b.checked = on);
  };
  const bulk = async (action) => {
    const ids = $$('.pick').filter((b) => b.checked).map((b) => Number(b.value));
    if (!ids.length) return toast('请先勾选申请', 'err');
    let reason = '批量审核通过';
    if (action === 'reject') { reason = prompt('批量拒绝原因', '不符合平台规范'); if (!reason) return; }
    try {
      const r = await api('/api/admin/domains/bulk', { method: 'POST', body: JSON.stringify({ ids, action, reason }) });
      toast(`处理完成：成功 ${r.ok}，失败 ${r.failed.length}`, 'ok'); route();
    } catch (e) { toast(e.message, 'err'); }
  };
  $('#bulk-ok').onclick = () => bulk('approve');
  $('#bulk-rj').onclick = () => bulk('reject');
}

async function adminDomains(status = 'all', q = '', page = 1) {
  const d = await api(`/api/admin/domains?status=${encodeURIComponent(status)}&q=${encodeURIComponent(q)}&page=${page}&size=20`);
  const filters = [['all', '全部'], ['active', '已激活'], ['pending', '待审核'], ['suspended', '已停用'], ['expired', '已过期']];
  const rows = d.items.map((x) => `
    <tr><td><div class="cell-main mono">${esc(x.fqdn)}</div><div class="cell-sub">${esc(x.owner_email)}</div></td>
      <td>${statusPill(x.status)}</td><td class="mono">${x.hit_count}</td><td class="mono">${x.dns_count}</td>
      <td class="tiny">${dateOnly(x.expires_at)}<br>${daysText(x)}</td>
      <td><div class="bar">
        ${x.status === 'pending' ? `<button class="btn sm primary" data-ap="${x.id}">通过</button>` : ''}
        ${x.status === 'active' ? `<button class="btn sm" data-sus="${x.id}">停用</button>` : ''}
        ${['suspended', 'expired'].includes(x.status) ? `<button class="btn sm" data-res="${x.id}">恢复</button>` : ''}
        <button class="btn sm ghost" onclick="openDomain(${x.id})">详情</button>
        <button class="btn sm danger" data-del="${x.id}">删除</button>
      </div></td></tr>`).join('');
  layout(`
    <div class="card">
      <div class="bar" style="margin-bottom:14px">
        ${filters.map(([k, l]) => `<button class="btn sm ${status === k ? 'primary' : ''}" data-st="${k}">${l}</button>`).join('')}
        <div class="spacer"></div>
        <input class="input" id="aq" placeholder="搜索域名 / 所有者邮箱" style="max-width:250px" value="${esc(q)}">
      </div>
      ${d.items.length ? `<div class="table-wrap"><table><thead><tr>
        <th>域名 / 所有者</th><th>状态</th><th>访问</th><th>解析</th><th>有效期</th><th>操作</th>
      </tr></thead><tbody>${rows}</tbody></table></div>
        <div class="bar" style="margin-top:12px"><span class="muted tiny">共 ${d.total} 条</span></div>`
      : '<div class="empty"><strong>没有匹配的域名</strong></div>'}
    </div>
  `, '全部域名', `平台共 ${d.total} 个域名`);
  $$('[data-st]').forEach((b) => b.onclick = () => adminDomains(b.dataset.st));
  $('#aq').onkeydown = (e) => { if (e.key === 'Enter') adminDomains(status, e.target.value); };
  $$('[data-ap]').forEach((b) => b.onclick = () => adminApprove(b.dataset.ap));
  $$('[data-sus]').forEach((b) => b.onclick = async () => {
    const reason = prompt('停用原因', '涉嫌违规使用') || '';
    try { await api(`/api/admin/domains/${b.dataset.sus}/suspend`, { method: 'POST', body: JSON.stringify({ reason }) }); toast('已停用', 'ok'); route(); }
    catch (e) { toast(e.message, 'err'); }
  });
  $$('[data-res]').forEach((b) => b.onclick = async () => {
    try { await api(`/api/admin/domains/${b.dataset.res}/resume`, { method: 'POST' }); toast('已恢复', 'ok'); route(); }
    catch (e) { toast(e.message, 'err'); }
  });
  $$('[data-del]').forEach((b) => b.onclick = async () => {
    if (!confirm('强制删除该域名？该操作不可恢复。')) return;
    try { await api(`/api/admin/domains/${b.dataset.del}`, { method: 'DELETE' }); toast('已删除', 'ok'); route(); }
    catch (e) { toast(e.message, 'err'); }
  });
}

async function adminUsers(q = '', page = 1) {
  const d = await api(`/api/admin/users?q=${encodeURIComponent(q)}&page=${page}&size=20`);
  const rows = d.items.map((u) => `
    <tr><td><div class="cell-main">${esc(u.name)}</div><div class="cell-sub">${esc(u.email)}</div></td>
      <td><span class="pill ${u.role === 'admin' ? 'teal' : ''}">${u.role === 'admin' ? '管理员' : '用户'}</span></td>
      <td>${u.status === 'active' ? '<span class="pill ok">正常</span>' : '<span class="pill danger">封禁</span>'}</td>
      <td class="mono">${money(u.balance)}</td><td class="mono">${u.domain_count}</td>
      <td class="tiny">${fmt(u.created_at)}</td>
      <td><button class="btn sm" data-edit="${u.id}">编辑</button></td></tr>`).join('');
  layout(`
    <div class="card">
      <div class="bar" style="margin-bottom:14px"><h3 style="margin:0">用户（${d.total}）</h3><div class="spacer"></div>
        <input class="input" id="uq" placeholder="搜索邮箱 / 昵称" style="max-width:240px" value="${esc(q)}"></div>
      ${d.items.length ? `<div class="table-wrap"><table><thead><tr>
        <th>用户</th><th>角色</th><th>状态</th><th>余额</th><th>域名数</th><th>注册时间</th><th>操作</th>
      </tr></thead><tbody>${rows}</tbody></table></div>`
      : '<div class="empty"><strong>没有用户</strong></div>'}
    </div>`, '用户管理', '管理账号角色、状态与余额');
  $('#uq').onkeydown = (e) => { if (e.key === 'Enter') adminUsers(e.target.value); };
  $$('[data-edit]').forEach((b) => b.onclick = () => {
    const u = d.items.find((x) => x.id === Number(b.dataset.edit));
    const mask = document.createElement('div');
    mask.className = 'modal-mask';
    mask.innerHTML = `<div class="modal" style="max-width:420px">
      <div class="modal-head"><h3>编辑用户</h3><button class="icon-btn" id="ux">✕</button></div>
      <div class="field"><label>用户</label><input class="input" value="${esc(u.email)}" disabled></div>
      <div class="field"><label>角色</label><select class="input" id="u-role">
        <option value="user" ${u.role === 'user' ? 'selected' : ''}>普通用户</option>
        <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>管理员</option></select></div>
      <div class="field"><label>状态</label><select class="input" id="u-status">
        <option value="active" ${u.status === 'active' ? 'selected' : ''}>正常</option>
        <option value="banned" ${u.status === 'banned' ? 'selected' : ''}>封禁</option></select></div>
      <div class="field"><label>余额（元）</label><input class="input" id="u-bal" type="number" step="0.01" value="${u.balance}"></div>
      <div class="field"><label>重置密码（留空不修改）</label><input class="input" id="u-pw" type="password"></div>
      <button class="btn primary block" id="u-save">保存</button></div>`;
    document.body.appendChild(mask);
    $('#ux', mask).onclick = () => mask.remove();
    $('#u-save', mask).onclick = async () => {
      const body = { role: $('#u-role', mask).value, status: $('#u-status', mask).value, balance: Number($('#u-bal', mask).value) };
      const pw = $('#u-pw', mask).value; if (pw) body.password = pw;
      try { await api('/api/admin/users/' + u.id, { method: 'PATCH', body: JSON.stringify(body) }); toast('已保存', 'ok'); mask.remove(); route(); }
      catch (e) { toast(e.message, 'err'); }
    };
  });
}

async function adminOrders() {
  const d = await api('/api/admin/orders?size=50');
  const rows = d.items.map((o) => `
    <tr><td class="mono tiny">${esc(o.order_no)}</td><td>${esc(o.user_email)}</td>
      <td><span class="pill ${o.kind === 'renew' ? 'teal' : 'info'}">${o.kind === 'renew' ? '续费' : '充值'}</span></td>
      <td class="tiny mono">${esc(o.fqdn || '—')}</td><td class="mono">${money(o.amount)}</td>
      <td>${o.status === 'paid' ? '<span class="pill ok">已支付</span>' : `<span class="pill">${esc(o.status)}</span>`}</td>
      <td class="tiny">${fmt(o.created_at)}</td></tr>`).join('');
  layout(`<div class="card"><h3>订单流水（${d.total}）</h3>
    ${d.items.length ? `<div class="table-wrap"><table><thead><tr><th>订单号</th><th>用户</th><th>类型</th><th>域名</th><th>金额</th><th>状态</th><th>时间</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : '<div class="empty"><strong>暂无订单</strong></div>'}</div>`, '订单流水', '续费与充值记录');
}

async function adminAudit(q = '') {
  const d = await api(`/api/admin/audit?q=${encodeURIComponent(q)}&size=40`);
  const rows = d.items.map((a) => `
    <tr><td class="tiny mono">${fmt(a.ts)}</td><td><span class="pill">${esc(a.action)}</span></td>
      <td class="mono tiny">${esc(a.target)}</td><td class="tiny">${esc(a.detail || '')}</td>
      <td class="tiny">${esc(a.actor_name || 'system')}</td></tr>`).join('');
  layout(`<div class="card">
    <div class="bar" style="margin-bottom:14px"><h3 style="margin:0">审计日志</h3><div class="spacer"></div>
      <input class="input" id="lq" placeholder="搜索动作 / 对象" style="max-width:250px" value="${esc(q)}"></div>
    <div class="table-wrap"><table><thead><tr><th>时间</th><th>动作</th><th>对象</th><th>详情</th><th>操作人</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`, '审计日志', `共 ${d.total} 条记录`);
  $('#lq').onkeydown = (e) => { if (e.key === 'Enter') adminAudit(e.target.value); };
}

async function adminSettings() {
  const d = await api('/api/admin/settings');
  const s = d.settings;
  let reserved = [];
  try { reserved = JSON.parse(s.reserved_words || '[]'); } catch (e) { reserved = []; }
  const box = (label, inner) => `<div class="field"><label>${label}</label>${inner}</div>`;
  layout(`
    <div class="grid c2">
      <div class="card"><h3>基础设置</h3>
        ${box('站点名称', `<input class="input" id="s-site" value="${esc(s.site_name)}">`)}
        ${box('主域名（分发根域）', `<input class="input" id="s-md" value="${esc(s.main_domain)}" placeholder="example.com">`)}
        <div class="grid c2" style="gap:10px">
          ${box('年费（元）', `<input class="input" id="s-price" type="number" step="0.01" value="${esc(s.price_per_year)}">`)}
          ${box('默认年限', `<input class="input" id="s-years" type="number" min="1" max="10" value="${esc(s.default_years)}">`)}
        </div>
        <div class="grid c2" style="gap:10px">
          ${box('单用户域名上限', `<input class="input" id="s-max" type="number" min="1" value="${esc(s.max_domains_per_user)}">`)}
          ${box('申请自动审核', `<select class="input" id="s-auto">
            <option value="1" ${s.auto_approve === '1' ? 'selected' : ''}>开启（提交即生效）</option>
            <option value="0" ${s.auto_approve !== '1' ? 'selected' : ''}>关闭（人工审核）</option></select>`)}
        </div>
        ${box('平台公告', `<textarea class="input" id="s-notice">${esc(s.notice)}</textarea>`)}
      </div>
      <div>
        <div class="card"><h3>DNS 服务商</h3>
          ${box('当前服务商', `<select class="input" id="s-prov">
            ${d.providers.map((p) => `<option value="${p.key}" ${p.current ? 'selected' : ''}>${esc(p.label)}${p.configured ? '' : '（未配置）'}</option>`).join('')}
          </select>`)}
          <div class="tiny muted" style="margin:-4px 0 12px">未配置凭据时自动降级为本地托管，记录仍会保存。</div>
          <div class="nav-sep" style="margin:0 0 8px;color:var(--muted)">CLOUDFLARE</div>
          ${box('API Token', `<input class="input" id="s-cft" placeholder="${s.cf_api_token ? '已设置：' + s.cf_api_token + '（留空不修改）' : '粘贴 API Token'}">`)}
          ${box('Zone ID', `<input class="input" id="s-cfz" value="${esc(s.cf_zone_id || '')}" placeholder="Zone ID">`)}
          <div class="nav-sep" style="margin:12px 0 8px;color:var(--muted)">阿里云 DNS</div>
          ${box('AccessKey ID', `<input class="input" id="s-akid" placeholder="${s.aliyun_access_key_id ? '已设置：' + s.aliyun_access_key_id + '（留空不修改）' : 'AccessKey ID'}">`)}
          ${box('AccessKey Secret', `<input class="input" id="s-aksec" type="password" placeholder="${s.aliyun_access_key_secret ? '已设置（留空不修改）' : 'AccessKey Secret'}">`)}
        </div>
        <div class="card" style="margin-top:14px"><h3>保留词</h3>
          ${box('每行一个 / 逗号分隔', `<textarea class="input" id="s-reserved" style="min-height:110px">${esc(reserved.join('\n'))}</textarea>`)}
        </div>
      </div>
    </div>
    <div class="bar" style="margin-top:16px">
      <button class="btn primary" id="s-save">保存全部设置</button>
      <span class="tiny muted">修改主域名后，已分配域名的 fqdn 不会自动变更，请谨慎操作。</span>
    </div>
  `, '系统设置', '平台参数、审核策略与 DNS 服务商凭据');
  $('#s-save').onclick = async () => {
    const body = {
      site_name: $('#s-site').value.trim(), main_domain: $('#s-md').value.trim(),
      price_per_year: Number($('#s-price').value), default_years: Number($('#s-years').value),
      max_domains_per_user: Number($('#s-max').value), auto_approve: $('#s-auto').value === '1',
      notice: $('#s-notice').value.trim(), dns_provider: $('#s-prov').value,
      cf_zone_id: $('#s-cfz').value.trim(),
      reserved_words: $('#s-reserved').value.split(/[\n,，]/).map((x) => x.trim()).filter(Boolean),
    };
    const cft = $('#s-cft').value.trim(); if (cft) body.cf_api_token = cft;
    const akid = $('#s-akid').value.trim(); if (akid) body.aliyun_access_key_id = akid;
    const aksec = $('#s-aksec').value.trim(); if (aksec) body.aliyun_access_key_secret = aksec;
    try {
      await api('/api/admin/settings', { method: 'PUT', body: JSON.stringify(body) });
      toast('设置已保存', 'ok');
      state.config = await api('/api/auth/public-config');
      route();
    } catch (e) { toast(e.message, 'err'); }
  };
}
