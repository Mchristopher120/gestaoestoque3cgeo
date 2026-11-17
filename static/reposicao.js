// Reposição: estoque de segurança, ponto de pedido e cobertura
const R = { dados: null, sort: { key: 'ord_sit', dir: 1 } };

async function carregar(janela) {
    const url = '/api/reposicao' + (janela ? `?janela=${janela}` : '');
    if (!R.dados) $('tbodyRep').innerHTML = linhaCarregando(8);
    try { R.dados = await fetchJSON(url); }
    catch (err) { showToast(err.message, 'error'); $('tbodyRep').innerHTML = `<tr><td colspan="8" class="empty">${escapeHTML(err.message)}</td></tr>`; return; }
    R.dados.itens.forEach(l => { l.ord_sit = l.pedir ? 0 : (l.consumo === 0 ? 2 : 1); });
    $('selJanela').value = String(R.dados.janela);
    $('btnExport').href = `/api/reposicao.xlsx?janela=${R.dados.janela}`;
    renderCards();
    render();
}

function renderCards() {
    const d = R.dados, c = d.config;
    $('repCards').innerHTML = `
        <div class="kpi ${d.pedir ? 'red' : 'green'}">
            <div class="kpi-label">No ponto de pedido</div>
            <div class="kpi-value">${fmtNum(d.pedir)}</div>
            <div class="kpi-sub">${d.pedir ? 'itens para pedir agora' : 'nenhum item para pedir agora'}</div>
        </div>
        <div class="kpi accent">
            <div class="kpi-label">Itens monitorados</div>
            <div class="kpi-value">${fmtNum(d.itens.length)}</div>
            <div class="kpi-sub">${fmtNum(d.sem_consumo)} sem consumo nos últimos ${d.janela} dias</div>
        </div>
        <div class="kpi slate">
            <div class="kpi-label">Prazo de entrega</div>
            <div class="kpi-value">${fmtNum(c.prazo)} <span class="kpi-unit">dias</span></div>
            <div class="kpi-sub">igual para todos os itens</div>
        </div>
        <div class="kpi slate">
            <div class="kpi-label">Nível de serviço</div>
            <div class="kpi-value">${fmtNum(c.ns)}<span class="kpi-unit">%</span></div>
            <div class="kpi-sub">chance de não faltar no prazo</div>
        </div>`;
}

function filtrar() {
    const q = normalizar($('fBusca').value.trim()), so = $('fPedir').checked;
    return R.dados.itens.filter(l => (!so || l.pedir) && (!q || normalizar(`${l.codigo} ${l.descricao}`).includes(q)));
}

function situacaoBadge(l) {
    if (l.pedir) return '<span class="badge critico">' + ico('alert-triangle') + ' Pedir agora</span>';
    if (l.consumo === 0) return '<span class="badge neutro">Sem consumo</span>';
    return '<span class="badge ok">' + ico('circle-check') + ' Estoque ok</span>';
}

function render() {
    const lista = ordenar(filtrar(), R.sort.key, R.sort.dir);
    $('countBadge').textContent = `${fmtNum(lista.length)} ${lista.length === 1 ? 'item' : 'itens'}`;
    if (!lista.length) {
        $('tbodyRep').innerHTML = `<tr><td colspan="8" class="empty"><span class="empty-icon">${ico('chart-bar', 'ico ico-empty')}</span>${R.dados.itens.length ? 'Nenhum item encontrado.' : 'Cadastre itens e registre saídas para ver a análise.'}</td></tr>`;
        return;
    }
    $('tbodyRep').innerHTML = lista.map(l => {
        const calc = l.consumo > 0;
        return `<tr class="${l.pedir ? 'row-alerta' : ''}">
            <td class="text-left"><a href="/estoque?id=${l.id}">${escapeHTML(l.descricao)}</a>
                <span class="forn-sub">${escapeHTML(l.codigo)}${l.poucos_dados && l.consumo > 0 ? ` · <span class="text-amber" title="Menos de 30 dias de histórico: cálculo pouco confiável">${l.dias_base} dia(s) de dados</span>` : ''}</span></td>
            <td class="num nowrap"><strong>${fmtNum(l.saldo)}</strong> <span class="muted small">${escapeHTML(l.unidade)}</span></td>
            <td class="num">${calc ? fmtNum(l.consumo_dia) : '<span class="muted">—</span>'}</td>
            <td class="num">${calc ? fmtNum(l.seguranca) : '<span class="muted">—</span>'}</td>
            <td class="num">${calc ? `<strong>${fmtNum(l.ponto_pedido)}</strong>` : '<span class="muted">—</span>'}</td>
            <td class="num">${l.cobertura_dias !== null ? fmtNum(l.cobertura_dias) : '<span class="muted">—</span>'}</td>
            <td>${situacaoBadge(l)}</td>
            <td class="num nowrap">${l.qtd_sugerida !== null ? `<strong>${fmtNum(l.qtd_sugerida)}</strong> <span class="muted small">${escapeHTML(l.unidade)}</span>` : (l.pedir ? '<span class="muted small" title="Defina o estoque máximo do item">defina o máx.</span>' : '<span class="muted">—</span>')}</td>
        </tr>`;
    }).join('');
}

// Período de análise
$('selJanela').addEventListener('change', async () => {
    try { await enviarJSON('/api/config', 'PUT', { janela: $('selJanela').value }); } catch { /* só não persiste */ }
    carregar(+$('selJanela').value);
});

// Parâmetros (prazo de entrega e nível de serviço, iguais para todos os itens)
$('btnParam').addEventListener('click', () => {
    const c = R.dados.config;
    $('parPrazo').value = String(c.prazo); $('parNs').value = String(c.ns).replace('.', ',');
    $('paramErro').hidden = true;
    abrirModal('modalParam');
});
$('paramCancelar').addEventListener('click', () => fecharModal('modalParam'));
$('formParam').addEventListener('submit', async ev => {
    ev.preventDefault();
    try {
        const r = await enviarJSON('/api/config', 'PUT', { prazo: $('parPrazo').value, ns: $('parNs').value });
        if (!r.ok) { $('paramErro').firstElementChild.textContent = r.error; $('paramErro').hidden = false; return; }
        fecharModal('modalParam');
        showToast('Parâmetros salvos.', 'success');
        carregar(R.dados.janela);
    } catch (err) { $('paramErro').firstElementChild.textContent = err.message; $('paramErro').hidden = false; }
});

['fBusca', 'fPedir'].forEach(id => $(id).addEventListener('input', render));
ativarOrdenacao($('tblRep'), R.sort, render);
carregar();
