// Painel (página inicial)
let carregouPainel = false;

async function carregarPainel({ aviso = false } = {}) {
    const erroBox = $('erroBox');
    if (!carregouPainel) {
        $('kpis').innerHTML = Array(6).fill('<div class="kpi skeleton"></div>').join('');
        $('tbodyUltimas').innerHTML = linhaCarregando(6);
    }
    try {
        const [s, ult] = await Promise.all([fetchJSON('/api/stats'), fetchJSON('/api/movimentos?limite=8')]);
        erroBox.hidden = true;
        carregouPainel = true;
        renderAtencao(s);
        renderKPIs(s);
        marcarAlertas(s.criticos_total);
        renderGraficos(s);
        renderUltimas(ult);
        if (aviso) showToast('Dados atualizados', 'success');
    } catch (err) {
        $('erroMsg').textContent = err.message;
        erroBox.hidden = false;
        if (!carregouPainel) {
            $('kpis').innerHTML = '';
            $('tbodyUltimas').innerHTML = `<tr><td colspan="6" class="empty">Dados indisponíveis no momento.</td></tr>`;
            ['chartSituacao', 'listaCriticos', 'chartCategorias', 'chartEvolucao', 'chartTopSaldo', 'chartTopSaidas']
                .forEach(id => $(id).innerHTML = graficoVazio('Dados indisponíveis.'));
        }
    }
}

function barraKpi(valor, cor, rotulo) {
    const p = Math.min(100, Math.max(0, parseFloat(valor) || 0));
    return `<div class="kpi-bar" role="progressbar" aria-label="${escapeHTML(rotulo)}" aria-valuenow="${Math.round(p)}" aria-valuemin="0" aria-valuemax="100"><span style="width:${p}%;background:${cor}"></span></div>`;
}

function renderKPIs(s) {
    const sit = s.situacao;
    const pctOk = s.itens_ativos ? ((sit.ok + sit.excesso) / s.itens_ativos) * 100 : 0;
    $('kpis').innerHTML = `
        <div class="kpi accent">
            <div class="kpi-label">Itens ativos</div>
            <div class="kpi-value">${fmtNum(s.itens_ativos)}</div>
            <div class="kpi-sub">${s.itens_arquivados ? `${fmtNum(s.itens_arquivados)} arquivado${s.itens_arquivados > 1 ? 's' : ''}` : 'cadastrados no estoque'}</div>
        </div>
        <div class="kpi ${s.criticos_total ? 'red' : 'green'}">
            <div class="kpi-label">Para repor</div>
            <div class="kpi-value">${fmtNum(s.criticos_total)}</div>
            <div class="kpi-sub">${fmtNum(sit.zerado)} zerado${sit.zerado === 1 ? '' : 's'} · ${fmtNum(sit.baixo)} abaixo do mínimo</div>
            ${barraKpi(pctOk, 'var(--green)', 'Itens com estoque adequado')}
        </div>
        <a class="kpi ${s.no_ponto_pedido ? 'amber' : 'green'}" href="/reposicao" style="text-decoration:none;color:inherit" title="Ver na tela Reposição">
            <div class="kpi-label">No ponto de pedido</div>
            <div class="kpi-value">${fmtNum(s.no_ponto_pedido)}</div>
            <div class="kpi-sub">hora de pedir ao fornecedor</div>
        </a>
        <div class="kpi green">
            <div class="kpi-label">Entradas no mês</div>
            <div class="kpi-value">${fmtNum(s.entradas_mes)}</div>
            <div class="kpi-sub">lançamentos de recebimento</div>
        </div>
        <div class="kpi amber">
            <div class="kpi-label">Saídas no mês</div>
            <div class="kpi-value">${fmtNum(s.saidas_mes)}</div>
            <div class="kpi-sub">lançamentos de saída</div>
        </div>
        <div class="kpi slate">
            <div class="kpi-label">Movimentações no mês</div>
            <div class="kpi-value">${fmtNum(s.movimentos_mes)}</div>
            <div class="kpi-sub">entradas, saídas e ajustes</div>
        </div>`;
}

function renderAtencao(s) {
    const el = $('atencao');
    const itens = [];
    if (s.situacao.zerado) itens.push({ icone: 'package-off', cls: 'critico', filtro: 'zerado',
        texto: `<strong>${fmtNum(s.situacao.zerado)}</strong> item${s.situacao.zerado > 1 ? 's zerados' : ' zerado'}` });
    if (s.situacao.baixo) itens.push({ icone: 'alert-triangle', cls: 'aviso', filtro: 'baixo',
        texto: `<strong>${fmtNum(s.situacao.baixo)}</strong> abaixo do estoque mínimo` });
    if (!itens.length) {
        el.innerHTML = s.itens_ativos
            ? `<div class="atencao-ok">${ico('circle-check')} Estoque em dia: nenhum item zerado ou abaixo do mínimo.</div>` : '';
        return;
    }
    el.innerHTML = `<span class="atencao-titulo">${ico('bell')} Precisa de atenção</span>` + itens.map(i => `
        <a class="atencao-item ${i.cls}" href="/estoque?situacao=${i.filtro}">${ico(i.icone)}<span>${i.texto}</span>${ico('arrow-left', 'ico ico-seta')}</a>`).join('');
}

function renderGraficos(s) {
    const sit = s.situacao;
    graficoRosca($('chartSituacao'), [
        { label: 'Normal', value: sit.ok, color: 'var(--green)' },
        { label: 'Abaixo do mínimo', value: sit.baixo, color: 'var(--amber)' },
        { label: 'Zerado', value: sit.zerado, color: 'var(--red)' },
        { label: 'Acima do máximo', value: sit.excesso, color: 'var(--info)' },
    ], 'itens', 'Cadastre itens para ver a situação do estoque.');
    listaCriticos($('listaCriticos'), s.criticos, s.criticos_total);
    graficoRanking($('chartCategorias'), s.categorias.map(c => ({
        label: c.categoria, value: c.itens, texto: `${fmtNum(c.itens)} ${c.itens === 1 ? 'item' : 'itens'}`,
    })), 'var(--primary)', 'Nenhum item cadastrado ainda.');
    graficoEvolucao($('chartEvolucao'), s.evolucao);
    graficoRanking($('chartTopSaldo'), s.top_saldo.map(i => ({
        label: i.descricao, sub: i.codigo, value: i.saldo, texto: `${fmtNum(i.saldo)} ${i.unidade}`,
    })), 'var(--liq-strong)', 'Registre entradas para ver este ranking.');
    graficoRanking($('chartTopSaidas'), s.top_saidas.map(i => ({
        label: i.descricao, sub: i.codigo, value: i.qtde, texto: `${fmtNum(i.qtde)} ${i.unidade}`,
    })), 'var(--amber)', 'Nenhuma saída nos últimos 30 dias.');
}

function renderUltimas(lista) {
    $('tbodyUltimas').innerHTML = lista.length ? lista.map(m => `
        <tr>
            <td class="nowrap">${dataBR(m.data)}</td>
            <td>${badgeTipo(m.tipo)}</td>
            <td class="text-left"><a href="/estoque?id=${m.item_id}">${escapeHTML(m.descricao)}</a><span class="forn-sub">${escapeHTML(m.codigo)}</span></td>
            <td class="num nowrap">${qtdeSinal(m.qtde, m.unidade)}</td>
            <td>${escapeHTML(m.documento) || '<span class="muted">—</span>'}</td>
            <td>${escapeHTML(m.usuario)}</td>
        </tr>`).join('')
        : `<tr><td colspan="6" class="empty"><span class="empty-icon">${ico('arrows-exchange', 'ico ico-empty')}</span>Nenhuma movimentação registrada ainda.</td></tr>`;
}

$('btnRefresh').addEventListener('click', () => carregarPainel({ aviso: true }));
$('btnTentar').addEventListener('click', () => carregarPainel());
carregarPainel();
