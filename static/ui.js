// Utilitários compartilhados pelas telas (Dashboard, Empenhos, Histórico).

const fmtMoney = (v) => new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v || 0);
const fmtMoneyCurto = (v) => new Intl.NumberFormat('pt-BR', {
    style: 'currency', currency: 'BRL', notation: 'compact', maximumFractionDigits: 1,
}).format(v || 0);
const fmtNum = (v) => new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 3 }).format(v ?? 0);
const escapeHTML = (str) => String(str ?? '').replace(/[&<>"']/g, m => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[m]));

/** Percentual no padrão brasileiro: 12,5% */
function pct(v) {
    return `${(parseFloat(v) || 0).toFixed(1).replace('.', ',')}%`;
}

/** '2026-08-12' -> '12/08/2026' (e '2026-08-12 10:30:00' -> '12/08/2026 10:30') */
function dataBR(s) {
    if (!s) return '';
    const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
    if (!m) return String(s);
    return `${m[3]}/${m[2]}/${m[1]}` + (m[4] ? ` ${m[4]}:${m[5]}` : '');
}

/**
 * Converte o que a pessoa digitou em número, aceitando os dois jeitos:
 *   '1.234,56' -> 1234.56   '22,5' -> 22.5   '22.50' -> 22.5   '1.000' -> 1000
 * (Antes, '22.50' virava 2250 porque todo ponto era tratado como milhar.)
 */
function parseNumBR(v) {
    if (typeof v === 'number') return v;
    let s = String(v ?? '').trim().replace(/R\$|\s/g, '');
    if (!s) return 0;
    if (s.includes(',')) {
        s = s.replace(/\./g, '').replace(',', '.');
    } else if (s.includes('.')) {
        const umPontoDecimal = (s.match(/\./g) || []).length === 1 && /\.\d{1,2}$/.test(s);
        if (!umPontoDecimal) s = s.replace(/\./g, '');
    }
    const n = parseFloat(s);
    return Number.isFinite(n) ? n : 0;
}

/** Cor do percentual executado: verde (>=90), âmbar (>=50), vermelho. */
function corPct(v) {
    if (v >= 90) return 'var(--green)';
    if (v >= 50) return 'var(--amber)';
    return 'var(--red)';
}

/** Célula de % com mini barra de progresso. */
function pctCell(v, rotulo = 'liquidado') {
    const p = Math.min(100, Math.max(0, parseFloat(v) || 0));
    return `<div class="pct-cell" title="${pct(v)} ${rotulo}">
        <span class="pct-num">${pct(v)}</span>
        <span class="progress"><span style="width:${p}%;background:${corPct(p)}"></span></span>
    </div>`;
}

/** fetch que lança erro legível quando a API falha (ex.: banco Neon dormindo)
 *  e manda para o login quando a sessão expira. */
async function fetchJSON(url, opts) {
    let res;
    try {
        res = await fetch(url, opts);
    } catch {
        throw new Error('Sem conexão com o servidor.');
    }
    let data = null;
    try { data = await res.json(); } catch { /* corpo não-JSON */ }
    if (res.status === 401) {
        location.href = `/login?next=${encodeURIComponent(location.pathname + location.search)}`;
        throw new Error('Sessão expirada. Entre novamente.');
    }
    if (!res.ok && !(data && 'ok' in data)) {
        throw new Error((data && (data.mensagem || data.error)) || `Erro ${res.status} ao carregar dados.`);
    }
    return data;
}

/** POST/PUT/DELETE com JSON. */
function enviarJSON(url, metodo, corpo) {
    return fetchJSON(url, {
        method: metodo, headers: { 'Content-Type': 'application/json' },
        body: corpo === undefined ? undefined : JSON.stringify(corpo),
    });
}

// ---------- Toast ----------
let toastTimer;
function showToast(msg, type = '') {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = `toast show ${type}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.className = 'toast', type === 'error' ? 5000 : 3500);
}

// ---------- Ordenação de tabelas ----------
// Cabeçalhos ordenáveis: <th data-key="campo" [data-default="desc"]>
function ordenar(rows, key, dir) {
    if (!key) return rows;
    return [...rows].sort((a, b) => {
        const x = a[key], y = b[key];
        if (typeof x === 'number' || typeof y === 'number') return ((+x || 0) - (+y || 0)) * dir;
        return String(x ?? '').localeCompare(String(y ?? ''), 'pt-BR', { numeric: true, sensitivity: 'base' }) * dir;
    });
}

function ativarOrdenacao(table, sortState, onChange) {
    table.querySelectorAll('th[data-key]').forEach(th => {
        th.tabIndex = 0;
        th.classList.add('sortable');
        const go = () => {
            if (sortState.key === th.dataset.key) sortState.dir *= -1;
            else { sortState.key = th.dataset.key; sortState.dir = th.dataset.default === 'desc' ? -1 : 1; }
            table.querySelectorAll('th[data-key]').forEach(t => t.removeAttribute('aria-sort'));
            th.setAttribute('aria-sort', sortState.dir > 0 ? 'ascending' : 'descending');
            onChange();
        };
        th.addEventListener('click', go);
        th.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
        });
    });
}

/** Linha de "carregando" para tabelas. */
function linhaCarregando(colspan) {
    return `<tr><td colspan="${colspan}" class="loading-row"><span class="spinner"></span> Carregando…</td></tr>`;
}

/** Remove acentos e caixa para busca. */
const normalizar = (s) => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

/** Reduz a fonte de valores grandes (ex.: R$ 1.234.567,89) até caberem no card. */
function ajustarValores(container) {
    if (!container) return;
    container.querySelectorAll('.kpi-value').forEach(el => {
        el.style.fontSize = '';
        let tam = parseFloat(getComputedStyle(el).fontSize);
        while (el.scrollWidth > el.clientWidth && tam > 14) {
            tam -= 1;
            el.style.fontSize = tam + 'px';
        }
    });
}
let _ajusteTimer;
window.addEventListener('resize', () => {
    clearTimeout(_ajusteTimer);
    _ajusteTimer = setTimeout(() => ajustarValores(document.getElementById('kpis')), 150);
});

/** Contador vermelho no item "Estoque" da barra: itens zerados + abaixo do mínimo. */
function marcarAlertas(n) {
    const el = document.getElementById('navPend');
    if (!el) return;
    el.hidden = !n;
    el.textContent = n > 99 ? '99+' : String(n || '');
    const txt = `${n} item(ns) para repor`;
    el.title = txt;
    el.setAttribute('aria-label', txt);
}
async function atualizarAlertas() {
    try { const r = await fetchJSON('/api/alertas'); marcarAlertas(r.repor); } catch { /* sem alerta */ }
}
document.addEventListener('DOMContentLoaded', atualizarAlertas);

const $ = (id) => document.getElementById(id);

/** Janelas (modais): abrir/fechar com Esc e clique fora. */
function abrirModal(id) {
    const m = $(id);
    m.style.display = 'flex';
    const box = m.querySelector('.modal-box'); if (box) box.scrollTop = 0;
    const alvo = m.querySelector('input:not([type=hidden]):not([type=radio]), select, textarea');
    setTimeout(() => alvo && alvo.focus({ preventScroll: true }), 30);
}
function fecharModal(id) { $(id).style.display = 'none'; }
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') document.querySelectorAll('.modal').forEach(m => { m.style.display = 'none'; });
});
document.addEventListener('mousedown', e => {
    if (e.target.classList && e.target.classList.contains('modal')) e.target.style.display = 'none';
});

/** Rótulos e cores das movimentações. */
const TIPO_MOV = {
    ENTRADA: { rot: 'Entrada', icone: 'arrow-down', cls: 'ok' },
    SAIDA: { rot: 'Saída', icone: 'arrow-up', cls: 'atencao' },
    AJUSTE: { rot: 'Ajuste', icone: 'adjustments', cls: 'info' },
};
const SITUACAO = {
    ok: { rot: 'Normal', cls: 'ok', icone: 'circle-check' },
    baixo: { rot: 'Abaixo do mínimo', cls: 'atencao', icone: 'alert-triangle' },
    zerado: { rot: 'Zerado', cls: 'critico', icone: 'package-off' },
    excesso: { rot: 'Acima do máximo', cls: 'info', icone: 'package' },
};
const badgeTipo = (t) => { const x = TIPO_MOV[t] || { rot: t, icone: 'history', cls: 'neutro' }; return `<span class="badge ${x.cls}">${ico(x.icone)} ${x.rot}</span>`; };
const badgeSituacao = (s) => { const x = SITUACAO[s] || SITUACAO.ok; return `<span class="badge ${x.cls}">${ico(x.icone)} ${x.rot}</span>`; };
/** Quantidade com sinal e cor: +10 / −3 */
function qtdeSinal(q, und) {
    const v = parseFloat(q) || 0;
    return `<strong class="${v >= 0 ? 'text-green' : 'text-amber'}">${v > 0 ? '+' : v < 0 ? '−' : ''}${fmtNum(Math.abs(v))}</strong> <span class="muted small">${escapeHTML(und || '')}</span>`;
}
