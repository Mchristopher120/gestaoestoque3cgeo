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
    const topo = Math.max(4, [1, 2, 2.5, 4, 5, 10].map(f => f * mag).find(v => v >= max));
    const NOMES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
    el.innerHTML = `
    <div class="evo">
        <div class="evo-grid">
            ${[0, 0.25, 0.5, 0.75, 1].map(f => `<div class="evo-line" style="bottom:${f * 100}%"><span>${fmtNum(Math.round(topo * f))}</span></div>`).join('')}
        </div>
        <div class="evo-cols">
            ${meses.map(m => {
                const [a, mm] = m.mes.split('-');
                const rot = `${NOMES[+mm - 1]}/${a.slice(2)}`;
                return `
                <div class="evo-col" tabindex="0" title="${rot} — Entradas ${fmtNum(m.entradas)} • Saídas ${fmtNum(m.saidas)}">
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

/** Curva ABC (Pareto): barras = % do consumo de cada item; linha = % acumulado. itens: [{codigo, descricao, pct, pct_acum, classe, consumo, unidade}] */
function graficoPareto(el, itens, msgVazio) {
    const lista = itens.filter(i => i.classe).slice(0, 25);
    if (!lista.length) { el.innerHTML = graficoVazio(msgVazio || 'Sem saídas no período para montar a curva.'); return; }
    const W = 900, H = 330, ML = 46, MR = 46, MT = 14, MB = 78;
    const pw = W - ML - MR, ph = H - MT - MB;
    const maxPct = Math.max(5, Math.ceil(Math.max(...lista.map(i => i.pct)) / 5) * 5);
    const bw = pw / lista.length;
    const COR = { A: 'var(--primary)', B: 'var(--amber)', C: '#8a94a8' };
    const yR = v => MT + ph - (v / 100) * ph;          // eixo direito: % acumulado
    const yL = v => MT + ph - (v / maxPct) * ph;       // eixo esquerdo: % individual
    const barras = lista.map((i, k) => {
        const x = ML + k * bw + bw * 0.14, w = bw * 0.72, y = yL(i.pct);
        return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${(MT + ph - y).toFixed(1)}" rx="2" fill="${COR[i.classe]}" opacity=".9">
            <title>${escapeHTML(i.codigo)} — ${escapeHTML(i.descricao)}\nClasse ${i.classe} · ${fmtNum(i.consumo)} ${escapeHTML(i.unidade)} (${pct(i.pct)})\nAcumulado: ${pct(i.pct_acum)}</title></rect>`;
    }).join('');
    const pts = lista.map((i, k) => `${(ML + k * bw + bw / 2).toFixed(1)},${yR(i.pct_acum).toFixed(1)}`);
    const linha = `<polyline points="${pts.join(' ')}" fill="none" stroke="var(--text)" stroke-width="2" stroke-linejoin="round" opacity=".75"/>` +
        pts.map(p => `<circle cx="${p.split(',')[0]}" cy="${p.split(',')[1]}" r="3" fill="var(--text)" opacity=".75"/>`).join('');
    const rotulos = lista.map((i, k) => {
        const x = ML + k * bw + bw / 2;
        return `<text x="${x.toFixed(1)}" y="${MT + ph + 12}" transform="rotate(-45 ${x.toFixed(1)} ${MT + ph + 12})" text-anchor="end" class="pareto-lbl">${escapeHTML(i.codigo)}</text>`;
    }).join('');
    const gradeR = [0, 20, 40, 60, 80, 100].map(v => `<line x1="${ML}" x2="${W - MR}" y1="${yR(v)}" y2="${yR(v)}" class="pareto-grid"/>
        <text x="${W - MR + 6}" y="${yR(v) + 4}" class="pareto-ax">${v}%</text>`).join('');
    const ticksL = [0, 0.25, 0.5, 0.75, 1].map(f => `<text x="${ML - 6}" y="${yL(maxPct * f) + 4}" text-anchor="end" class="pareto-ax">${Math.round(maxPct * f)}%</text>`).join('');
    const ref = [80, 95].map(v => `<line x1="${ML}" x2="${W - MR}" y1="${yR(v)}" y2="${yR(v)}" class="pareto-ref"/>`).join('');
    el.innerHTML = `
    <div class="pareto-scroll"><svg viewBox="0 0 ${W} ${H}" class="pareto" role="img" aria-label="Curva ABC: % do consumo por item e % acumulado">
        ${gradeR}${ref}${barras}${linha}${ticksL}${rotulos}
    </svg></div>
    <div class="legend">
        <span><i style="background:var(--primary)"></i>Classe A (até 80%)</span>
        <span><i style="background:var(--amber)"></i>Classe B (até 95%)</span>
        <span><i style="background:#8a94a8"></i>Classe C (resto)</span>
        <span><i style="background:var(--text);opacity:.75;height:3px;border-radius:2px"></i>% acumulado (eixo direito)</span>
    </div>
    ${itens.filter(i => i.classe).length > lista.length ? `<p class="muted small">Mostrando os ${lista.length} itens de maior consumo.</p>` : ''}`;
}
