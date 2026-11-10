// Reposição: curva ABC, estoque de segurança e ponto de pedido
const R = { dados: null, sort: { key: 'ord_classe', dir: 1 } };
const ORD_CLASSE = { A: 0, B: 1, C: 2 };
const COR_CLASSE = { A: 'info', B: 'atencao', C: 'neutro' };

async function carregar(janela) {
    const url = '/api/reposicao' + (janela ? `?janela=${janela}` : '');
    if (!R.dados) $('tbodyRep').innerHTML = linhaCarregando(10);
    try { R.dados = await fetchJSON(url); }
    catch (err) { showToast(err.message, 'error'); $('tbodyRep').innerHTML = `<tr><td colspan="10" class="empty">${escapeHTML(err.message)}</td></tr>`; return; }
    R.dados.itens.forEach(l => {
        l.ord_classe = l.classe ? ORD_CLASSE[l.classe] : 3;
        l.ord_sit = l.pedir ? 0 : (l.prazo === 0 && l.consumo > 0 ? 1 : (l.consumo === 0 ? 3 : 2));
    });
    $('selJanela').value = String(R.dados.janela);
    $('btnExport').href = `/api/reposicao.xlsx?janela=${R.dados.janela}`;
    $('subPareto').textContent = `Itens ordenados pela quantidade que saiu nos últimos ${R.dados.janela} dias`;
    renderCards();
    graficoPareto($('chartPareto'), R.dados.itens.filter(l => l.classe).sort((a, b) => a.pct_acum - b.pct_acum));
    render();
}

function renderCards() {
    const d = R.dados, r = d.resumo;
    const card = (cls, rot, c) => `
        <div class="kpi ${cls}">
            <div class="kpi-label">Classe ${rot}</div>
            <div class="kpi-value">${fmtNum(c.itens)} <span class="kpi-unit">${c.itens === 1 ? 'item' : 'itens'}</span></div>
            <div class="kpi-sub">${pct(c.pct_consumo)} do consumo · nível de serviço ${fmtNum(c.nivel_servico)}%</div>
        </div>`;
    $('abcCards').innerHTML =
        card('accent', 'A', r.A) + card('amber', 'B', r.B) + card('slate', 'C', r.C) + `
        <div class="kpi ${d.pedir ? 'red' : 'green'}">
            <div class="kpi-label">No ponto de pedido</div>
            <div class="kpi-value">${fmtNum(d.pedir)}</div>
            <div class="kpi-sub">${d.pedir ? 'peça ao fornecedor' : 'nenhum item para pedir agora'}</div>
        </div>`;
    const av = $('avisoPrazo');
    av.hidden = !d.sem_prazo;
    av.innerHTML = d.sem_prazo
        ? `${ico('alert-triangle')} ${fmtNum(d.sem_prazo)} ${d.sem_prazo === 1 ? 'item com consumo ainda não tem' : 'itens com consumo ainda não têm'} prazo de entrega. Preencha na tabela abaixo para calcular o ponto de pedido.` : '';
}

function filtrar() {
    const q = normalizar($('fBusca').value.trim()), cl = $('fClasse').value, so = $('fPedir').checked;
    return R.dados.itens.filter(l =>
        (!cl || (cl === '-' ? !l.classe : l.classe === cl)) && (!so || l.pedir) &&
        (!q || normalizar(`${l.codigo} ${l.descricao}`).includes(q)));
}

function situacaoBadge(l) {
    if (l.pedir) return '<span class="badge critico">' + ico('alert-triangle') + ' Pedir agora</span>';
    if (l.consumo === 0) return '<span class="badge neutro">Sem consumo</span>';
    if (l.prazo === 0) return '<span class="badge atencao">Defina o prazo</span>';
    return '<span class="badge ok">' + ico('circle-check') + ' Estoque ok</span>';
}

function render() {
    const lista = ordenar(filtrar(), R.sort.key, R.sort.dir);
    $('countBadge').textContent = `${fmtNum(lista.length)} ${lista.length === 1 ? 'item' : 'itens'}`;
    if (!lista.length) {
        $('tbodyRep').innerHTML = `<tr><td colspan="10" class="empty"><span class="empty-icon">${ico('chart-bar', 'ico ico-empty')}</span>${R.dados.itens.length ? 'Nenhum item encontrado.' : 'Cadastre itens e registre saídas para ver a análise.'}</td></tr>`;
        return;
    }
    $('tbodyRep').innerHTML = lista.map(l => {
        const calc = l.prazo > 0 && l.consumo > 0;
        return `<tr class="${l.pedir ? 'row-alerta' : ''}">
            <td>${l.classe ? `<span class="badge ${COR_CLASSE[l.classe]}">${l.classe}</span>` : '<span class="muted">—</span>'}</td>
            <td class="text-left"><a href="/estoque?id=${l.id}">${escapeHTML(l.descricao)}</a>
                <span class="forn-sub">${escapeHTML(l.codigo)}${l.poucos_dados && l.consumo > 0 ? ` · <span class="text-amber" title="Menos de 30 dias de histórico: cálculo pouco confiável">${l.dias_base} dia(s) de dados</span>` : ''}</span></td>
            <td class="num nowrap"><strong>${fmtNum(l.saldo)}</strong> <span class="muted small">${escapeHTML(l.unidade)}</span></td>
            <td class="num">${l.consumo > 0 ? fmtNum(l.consumo_dia) : '<span class="muted">—</span>'}</td>
            <td class="num"><input type="number" min="0" max="365" step="1" class="input input-prazo" data-prazo="${l.id}" value="${l.prazo || ''}" placeholder="0" aria-label="Prazo de entrega de ${escapeHTML(l.descricao)} em dias"></td>
            <td class="num">${calc ? fmtNum(l.seguranca) : '<span class="muted">—</span>'}</td>
            <td class="num">${calc ? `<strong>${fmtNum(l.ponto_pedido)}</strong>` : '<span class="muted">—</span>'}</td>
            <td class="num">${l.cobertura_dias !== null ? fmtNum(l.cobertura_dias) : '<span class="muted">—</span>'}</td>
            <td>${situacaoBadge(l)}</td>
            <td class="num nowrap">${l.qtd_sugerida !== null ? `<strong>${fmtNum(l.qtd_sugerida)}</strong> <span class="muted small">${escapeHTML(l.unidade)}</span>` : (l.pedir ? '<span class="muted small" title="Defina o estoque máximo do item">defina o máx.</span>' : '<span class="muted">—</span>')}</td>
        </tr>`;
    }).join('');
}

// Prazo de entrega direto na tabela
$('tbodyRep').addEventListener('change', async ev => {
    const inp = ev.target.closest('[data-prazo]');
    if (!inp) return;
    try {
        const r = await enviarJSON(`/api/itens/${inp.dataset.prazo}/prazo`, 'PUT', { prazo_entrega: inp.value || '0' });
        if (!r.ok) { showToast(r.error, 'error'); await carregar(R.dados.janela); return; }
        showToast('Prazo salvo.', 'success');
        await carregar(R.dados.janela);
    } catch (err) { showToast(err.message, 'error'); }
});

// Período de análise
$('selJanela').addEventListener('change', async () => {
    try { await enviarJSON('/api/config', 'PUT', { janela: $('selJanela').value }); } catch { /* só não persiste */ }
    carregar(+$('selJanela').value);
});

// Parâmetros (nível de serviço por classe)
$('btnParam').addEventListener('click', () => {
    const c = R.dados.config;
    $('nsA').value = String(c.ns_A).replace('.', ','); $('nsB').value = String(c.ns_B).replace('.', ','); $('nsC').value = String(c.ns_C).replace('.', ',');
    $('paramErro').hidden = true;
    abrirModal('modalParam');
});
$('paramCancelar').addEventListener('click', () => fecharModal('modalParam'));
$('formParam').addEventListener('submit', async ev => {
    ev.preventDefault();
    try {
        const r = await enviarJSON('/api/config', 'PUT', { ns_A: $('nsA').value, ns_B: $('nsB').value, ns_C: $('nsC').value });
        if (!r.ok) { $('paramErro').firstElementChild.textContent = r.error; $('paramErro').hidden = false; return; }
        fecharModal('modalParam');
        showToast('Parâmetros salvos.', 'success');
        carregar(R.dados.janela);
    } catch (err) { $('paramErro').firstElementChild.textContent = err.message; $('paramErro').hidden = false; }
});

['fBusca', 'fClasse', 'fPedir'].forEach(id => $(id).addEventListener('input', render));
ativarOrdenacao($('tblRep'), R.sort, render);
carregar();
