// Tela Estoque: lista de itens, cadastro/edição, ficha (kardex)
const E = { itens: [], sort: { key: null, dir: 1 }, editando: null, fichaId: null };
const ORD_SIT = { zerado: 0, baixo: 1, excesso: 2, ok: 3 };

async function carregar() {
    if (!E.itens.length) $('tbodyItens').innerHTML = linhaCarregando(9);
    try {
        E.itens = (await fetchJSON('/api/itens')).map(i => ({ ...i, ord_sit: ORD_SIT[i.situacao] }));
    } catch (err) {
        showToast(err.message, 'error');
        $('tbodyItens').innerHTML = `<tr><td colspan="9" class="empty">${escapeHTML(err.message)}</td></tr>`;
        return;
    }
    movConfigurar(E.itens, () => recarregarTudo());
    const cats = [...new Set(E.itens.map(i => i.categoria).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'pt-BR'));
    const atual = $('fCategoria').value;
    $('fCategoria').innerHTML = '<option value="">Todas as categorias</option>' + cats.map(c => `<option>${escapeHTML(c)}</option>`).join('');
    $('fCategoria').value = cats.includes(atual) ? atual : '';
    $('listaCats').innerHTML = cats.map(c => `<option value="${escapeHTML(c)}">`).join('');
    render();
}

async function recarregarTudo() {
    await carregar();
    if (E.fichaId && $('modalFicha').style.display === 'flex') abrirFicha(E.fichaId, false);
}

function filtrar() {
    const q = normalizar($('fBusca').value.trim()), sit = $('fSituacao').value, cat = $('fCategoria').value;
    const arq = $('fArquivados').checked;
    return E.itens.filter(i =>
        (arq || i.ativo) &&
        (!cat || i.categoria === cat) &&
        (!sit || (sit === 'repor' ? ['zerado', 'baixo'].includes(i.situacao) : i.situacao === sit)) &&
        (!q || normalizar(`${i.codigo} ${i.descricao} ${i.localizacao} ${i.categoria}`).includes(q)));
}

function render() {
    const lista = ordenar(filtrar(), E.sort.key, E.sort.dir);
    $('countBadge').textContent = `${fmtNum(lista.length)} ${lista.length === 1 ? 'item' : 'itens'}`;
    if (!lista.length) {
        $('tbodyItens').innerHTML = `<tr><td colspan="9" class="empty"><span class="empty-icon">${ico('package', 'ico ico-empty')}</span>
            <h2>${E.itens.length ? 'Nenhum item encontrado' : 'Nenhum item cadastrado'}</h2>
            ${E.itens.length ? 'Ajuste a busca ou os filtros.' : 'Clique em “Novo item” ou importe uma planilha.'}</td></tr>`;
        return;
    }
    $('tbodyItens').innerHTML = lista.map(i => `
        <tr class="${['zerado', 'baixo'].includes(i.situacao) && i.ativo ? 'row-alerta' : ''}${i.ativo ? '' : ' row-arquivado'}">
            <td class="nowrap"><strong>${escapeHTML(i.codigo)}</strong></td>
            <td class="text-left"><a href="#" data-ficha="${i.id}">${escapeHTML(i.descricao)}</a>
                <span class="forn-sub">${escapeHTML(i.localizacao) || ''}${!i.ativo ? ' · arquivado' : ''}</span></td>
            <td>${escapeHTML(i.categoria) || '<span class="muted">—</span>'}</td>
            <td class="num nowrap"><strong>${fmtNum(i.saldo)}</strong> <span class="muted small">${escapeHTML(i.unidade)}</span></td>
            <td class="num">${i.estoque_minimo ? fmtNum(i.estoque_minimo) : '<span class="muted">—</span>'}</td>
            <td class="num money">${i.custo_medio ? fmtMoney(i.custo_medio) : '<span class="muted">—</span>'}</td>
            <td class="num money">${i.valor_total ? fmtMoney(i.valor_total) : '<span class="muted">—</span>'}</td>
            <td>${i.ativo ? badgeSituacao(i.situacao) : '<span class="badge neutro">Arquivado</span>'}</td>
            <td class="acoes">
                ${i.ativo ? `<button class="btn btn-sm btn-secondary" data-mov="ENTRADA" data-id="${i.id}" title="Registrar entrada" aria-label="Entrada">${ico('arrow-down')}</button>
                <button class="btn btn-sm btn-secondary" data-mov="SAIDA" data-id="${i.id}" title="Registrar saída" aria-label="Saída">${ico('arrow-up')}</button>` : ''}
                <button class="btn btn-sm btn-secondary" data-ficha="${i.id}" title="Ficha e histórico do item" aria-label="Ficha">${ico('file-text')}</button>
                <button class="btn btn-sm btn-secondary" data-edit="${i.id}" title="Editar cadastro" aria-label="Editar">${ico('pencil')}</button>
            </td>
        </tr>`).join('');
}

// ---------- Cadastro / edição ----------
function abrirItem(item = null) {
    E.editando = item;
    $('formItem').reset();
    $('itemErro').hidden = true;
    $('itemTitulo').textContent = item ? 'Editar item' : 'Novo item';
    $('grupoInicial').hidden = !!item;
    if (item) {
        $('iCodigo').value = item.codigo; $('iDescricao').value = item.descricao; $('iUnidade').value = item.unidade;
        $('iCategoria').value = item.categoria || ''; $('iLocal').value = item.localizacao || '';
        $('iMin').value = item.estoque_minimo || ''; $('iMax').value = item.estoque_maximo || ''; $('iObs').value = item.observacoes || '';
    } else { $('iUnidade').value = 'UN'; }
    abrirModal('modalItem');
}

async function salvarItem(ev) {
    ev.preventDefault();
    const corpo = {
        codigo: $('iCodigo').value, descricao: $('iDescricao').value, unidade: $('iUnidade').value, categoria: $('iCategoria').value,
        localizacao: $('iLocal').value, estoque_minimo: $('iMin').value, estoque_maximo: $('iMax').value, observacoes: $('iObs').value,
    };
    if (!E.editando) { corpo.saldo_inicial = $('iSaldo').value; corpo.valor_unitario = $('iValor').value; }
    const btn = $('itemSalvar');
    btn.disabled = true;
    try {
        const r = await enviarJSON(E.editando ? `/api/itens/${E.editando.id}` : '/api/itens', E.editando ? 'PUT' : 'POST', corpo);
        if (!r.ok) { $('itemErro').firstElementChild.textContent = r.error; $('itemErro').hidden = false; return; }
        fecharModal('modalItem');
        showToast(E.editando ? 'Item atualizado.' : 'Item cadastrado.', 'success');
        await recarregarTudo();
        atualizarAlertas();
    } catch (err) {
        $('itemErro').firstElementChild.textContent = err.message; $('itemErro').hidden = false;
    } finally { btn.disabled = false; }
}

// ---------- Ficha (kardex) ----------
async function abrirFicha(id, abrir = true) {
    E.fichaId = id;
    if (abrir) { $('fichaCorpo').innerHTML = `<p class="loading-row"><span class="spinner"></span> Carregando…</p>`; abrirModal('modalFicha'); }
    let d;
    try { d = await fetchJSON(`/api/itens/${id}`); } catch (err) { showToast(err.message, 'error'); fecharModal('modalFicha'); return; }
    const i = d.item;
    const chip = (rot, val, cls = '') => `<span class="chip ${cls}">${rot}<strong>${val}</strong></span>`;
    $('fichaCorpo').innerHTML = `
        <div class="detail-head">
            <div>
                <div class="chips">${badgeSituacao(i.situacao)}${!i.ativo ? '<span class="badge neutro">Arquivado</span>' : ''}</div>
                <h3 id="fichaTitulo">${escapeHTML(i.descricao)}</h3>
                <div class="chips">
                    ${chip('Código', escapeHTML(i.codigo))}
                    ${chip('Saldo', `${fmtNum(i.saldo)} ${escapeHTML(i.unidade)}`, i.situacao === 'zerado' ? 'chip-red' : i.situacao === 'baixo' ? 'chip-amber' : 'chip-green')}
                    ${chip('Custo médio', fmtMoney(i.custo_medio))}
                    ${chip('Valor', fmtMoney(i.valor_total), 'chip-teal')}
                    ${i.estoque_minimo ? chip('Mínimo', fmtNum(i.estoque_minimo)) : ''}
                    ${i.estoque_maximo ? chip('Máximo', fmtNum(i.estoque_maximo)) : ''}
                    ${i.categoria ? chip('Categoria', escapeHTML(i.categoria)) : ''}
                    ${i.localizacao ? chip('Local', escapeHTML(i.localizacao)) : ''}
                </div>
                ${i.repor ? `<p class="campo-ajuda">Sugestão de reposição: cerca de <strong>${fmtNum(i.repor)} ${escapeHTML(i.unidade)}</strong>.</p>` : ''}
                ${i.observacoes ? `<p class="campo-ajuda">${escapeHTML(i.observacoes)}</p>` : ''}
            </div>
            <div class="detail-actions">
                ${i.ativo ? `<button class="btn btn-secondary btn-sm" data-fmov="ENTRADA">${ico('arrow-down')} Entrada</button>
                <button class="btn btn-secondary btn-sm" data-fmov="SAIDA">${ico('arrow-up')} Saída</button>
                <button class="btn btn-secondary btn-sm" data-fmov="AJUSTE">${ico('adjustments')} Ajuste</button>` : ''}
                <button class="btn btn-secondary btn-sm" data-farq="1">${ico('archive')} ${i.ativo ? 'Arquivar' : 'Reativar'}</button>
                ${!i.n_mov ? `<button class="btn btn-danger btn-sm" data-fdel="1">${ico('trash')} Excluir</button>` : ''}
            </div>
        </div>
        <h4>Histórico do item</h4>
        <div class="table-wrap">
            <table>
                <thead><tr><th>Data</th><th>Tipo</th><th>Quantidade</th><th>Saldo após</th><th>Documento</th><th>Origem / Destino</th><th>Usuário</th></tr></thead>
                <tbody>${d.movimentos.length ? d.movimentos.map(m => `
                    <tr><td class="nowrap">${dataBR(m.data)}</td><td>${badgeTipo(m.tipo)}</td>
                    <td class="num nowrap">${qtdeSinal(m.qtde, i.unidade)}</td><td class="num">${fmtNum(m.saldo_apos)}</td>
                    <td>${escapeHTML(m.documento) || '<span class="muted">—</span>'}</td>
                    <td>${escapeHTML(m.contraparte) || '<span class="muted">—</span>'}</td><td>${escapeHTML(m.usuario)}</td></tr>`).join('')
                    : `<tr><td colspan="7" class="empty">Sem movimentações ainda.</td></tr>`}</tbody>
            </table>
        </div>`;
    $('fichaCorpo').querySelectorAll('[data-fmov]').forEach(b => b.addEventListener('click', () => abrirMov(b.dataset.fmov, i.id)));
    const arq = $('fichaCorpo').querySelector('[data-farq]');
    if (arq) arq.addEventListener('click', async () => {
        const r = await enviarJSON(`/api/itens/${i.id}/arquivar`, 'POST');
        if (!r.ok) { showToast(r.error, 'error'); return; }
        showToast(r.ativo ? 'Item reativado.' : 'Item arquivado.', 'success');
        await recarregarTudo(); atualizarAlertas();
    });
    const del = $('fichaCorpo').querySelector('[data-fdel]');
    if (del) del.addEventListener('click', async () => {
        if (!confirm(`Excluir o item “${i.descricao}”? Isso não pode ser desfeito.`)) return;
        const r = await enviarJSON(`/api/itens/${i.id}`, 'DELETE');
        if (!r.ok) { showToast(r.error, 'error'); return; }
        fecharModal('modalFicha'); showToast('Item excluído.', 'success');
        await carregar(); atualizarAlertas();
    });
}

// ---------- Eventos ----------
$('tbodyItens').addEventListener('click', ev => {
    const b = ev.target.closest('[data-mov],[data-ficha],[data-edit]');
    if (!b) return;
    ev.preventDefault();
    const id = +(b.dataset.id || b.dataset.ficha || b.dataset.edit);
    if (b.dataset.mov) abrirMov(b.dataset.mov, id);
    else if (b.dataset.ficha) abrirFicha(id);
    else abrirItem(E.itens.find(i => i.id === id));
});
$('btnNovo').addEventListener('click', () => abrirItem());
$('formItem').addEventListener('submit', salvarItem);
$('itemCancelar').addEventListener('click', () => fecharModal('modalItem'));
$('fichaFechar').addEventListener('click', () => fecharModal('modalFicha'));
['fBusca', 'fSituacao', 'fCategoria', 'fArquivados'].forEach(id => $(id).addEventListener('input', render));
ativarOrdenacao($('tblItens'), E.sort, render);

(async () => {
    const p = new URLSearchParams(location.search);
    if (p.get('situacao')) $('fSituacao').value = p.get('situacao') === 'zerado' || p.get('situacao') === 'baixo' ? p.get('situacao') : '';
    await carregar();
    if (p.get('novo')) abrirItem();
    if (p.get('id')) abrirFicha(+p.get('id'));
})();
