// Gráficos leves em SVG/HTML puro (sem bibliotecas externas: funciona offline).

function graficoVazio(msg, icone = 'chart-bar') {
    return `<div class="chart-empty">${ico(icone, 'ico ico-empty')}${escapeHTML(msg)}</div>`;
}

/** Rosca. segmentos: [{label, value, color}] */
function graficoRosca(el, segmentos, rotuloCentro, msgVazio) {
    const total = segmentos.reduce((a, s) => a + (s.value || 0), 0);
    if (!total) { el.innerHTML = graficoVazio(msgVazio || 'Nada para mostrar ainda.'); return; }
    const R = 70, C = 2 * Math.PI * R, ESP = 22;
    const gap = segmentos.filter(s => s.value > 0).length > 1 ? 3 : 0;
    let offset = 0;
    const arcos = segmentos.map((s, idx) => {
        if (!s.value) return '';
        const len = (s.value / total) * C;
        const arco = `<circle class="donut-seg" data-idx="${idx}" r="${R}" cx="90" cy="90" fill="none"
            stroke="${s.color}" stroke-width="${ESP}"
            stroke-dasharray="${Math.max(0, len - gap)} ${C}" stroke-dashoffset="${-offset}">
            <title>${escapeHTML(s.label)}: ${fmtNum(s.value)} (${pct(s.value / total * 100)})</title></circle>`;
        offset += len;
        return arco;
    }).join('');
    el.innerHTML = `
    <div class="donut-wrap">
        <svg viewBox="0 0 180 180" class="donut" role="img" aria-label="${escapeHTML(rotuloCentro)}: ${fmtNum(total)}">
            <circle r="${R}" cx="90" cy="90" fill="none" stroke="var(--track)" stroke-width="${ESP}"/>
            <g transform="rotate(-90 90 90)">${arcos}</g>
            <text x="90" y="88" text-anchor="middle" class="donut-total">${fmtNum(total)}</text>
            <text x="90" y="110" text-anchor="middle" class="donut-label">${escapeHTML(rotuloCentro)}</text>
        </svg>
        <ul class="donut-legend">
            ${segmentos.map((s, idx) => `
            <li data-idx="${idx}"><i style="background:${s.color}"></i><span class="lg-label">${escapeHTML(s.label)}</span>
                <strong>${fmtNum(s.value)}</strong><span class="lg-pct">${pct(s.value / total * 100)}</span></li>`).join('')}
        </ul>
    </div>`;
    const marcar = (idx, on) => {
        el.querySelectorAll(`[data-idx="${idx}"]`).forEach(n => n.classList.toggle('hl', on));
        el.querySelector('.donut').classList.toggle('dim', on);
    };
    el.querySelectorAll('[data-idx]').forEach(n => {
        n.addEventListener('mouseenter', () => marcar(n.dataset.idx, true));
        n.addEventListener('mouseleave', () => marcar(n.dataset.idx, false));
    });
}

/** Ranking em barras horizontais. linhas: [{label, sub, value, texto, href}] */
function graficoRanking(el, linhas, cor, msgVazio) {
    if (!linhas.length) { el.innerHTML = graficoVazio(msgVazio); return; }
    const max = Math.max(...linhas.map(l => l.value)) || 1;
    el.innerHTML = `<ol class="rank">${linhas.map((l, i) => {
        const corpo = `
            <span class="rank-pos">${i + 1}</span>
            <div class="rank-body">
                <div class="rank-top"><span class="rank-label">${escapeHTML(l.label)}</span><strong class="rank-val">${escapeHTML(l.texto)}</strong></div>
                <div class="bar"><span style="width:${(l.value / max) * 100}%;background:${cor}"></span></div>
                ${l.sub ? `<div class="rank-sub">${escapeHTML(l.sub)}</div>` : ''}
            </div>`;
        return `<li title="${escapeHTML(l.label)}: ${escapeHTML(l.texto)}">${corpo}</li>`;
    }).join('')}</ol>`;
}

/** Colunas mensais (entradas × saídas). meses: [{mes:'2026-10', entradas, saidas}] */
function graficoEvolucao(el, meses) {
    const max = Math.max(0, ...meses.map(m => Math.max(m.entradas, m.saidas)));
    if (!max) { el.innerHTML = graficoVazio('Sem entradas ou saídas nos últimos 12 meses.'); return; }
    const mag = Math.pow(10, Math.floor(Math.log10(max)));
    const topo = [1, 2, 2.5, 5, 10].map(f => f * mag).find(v => v >= max);
    const NOMES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
    el.innerHTML = `
    <div class="evo">
        <div class="evo-grid">
            ${[0, 0.25, 0.5, 0.75, 1].map(f => `<div class="evo-line" style="bottom:${f * 100}%"><span>${fmtMoneyCurto(topo * f)}</span></div>`).join('')}
        </div>
        <div class="evo-cols">
            ${meses.map(m => {
                const [a, mm] = m.mes.split('-');
                const rot = `${NOMES[+mm - 1]}/${a.slice(2)}`;
                return `
                <div class="evo-col" tabindex="0" title="${rot} — Entradas ${fmtMoney(m.entradas)} • Saídas ${fmtMoney(m.saidas)}">
                    <div class="evo-bars">
                        <span class="evo-bar liq" style="height:${(m.entradas / topo) * 100}%"></span>
                        <span class="evo-bar saida" style="height:${(m.saidas / topo) * 100}%"></span>
                    </div>
                    <span class="evo-mes">${rot}</span>
                </div>`;
            }).join('')}
        </div>
    </div>`;
}

/** Lista "itens para repor". */
function listaCriticos(el, itens, total) {
    if (!itens.length) {
        el.innerHTML = `<div class="chart-empty ok">${ico('circle-check', 'ico ico-empty')}Nenhum item abaixo do mínimo.</div>`;
        return;
    }
    el.innerHTML = `<ul class="atrasos">${itens.map(c => `
        <li><a href="/estoque?id=${c.id}">
            <span class="atraso-dias ${c.situacao === 'baixo' ? 'amb' : ''}"><strong>${fmtNum(c.saldo)}</strong> ${escapeHTML(c.unidade)}</span>
            <span class="atraso-info">
                <strong>${escapeHTML(c.descricao)}</strong>
                <span>${escapeHTML(c.codigo)} · mínimo ${fmtNum(c.estoque_minimo)}${c.repor ? ` · repor ~${fmtNum(c.repor)}` : ''}</span>
            </span>
        </a></li>`).join('')}</ul>
        ${total > itens.length ? `<p class="muted small">+ ${total - itens.length} outro(s) — veja em Estoque.</p>` : ''}`;
}
