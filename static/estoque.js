// Tela Estoque: lista de itens, cadastro/edição, ficha (kardex)
const E = { itens: [], sort: { key: null, dir: 1 }, editando: null, fichaId: null, sel: new Set(), visao: 'lista' };
try { E.visao = localStorage.getItem('estoque_visao') === 'cards' ? 'cards' : 'lista'; } catch { /* sem storage */ }
const ORD_SIT = { zerado: 0, baixo: 1, excesso: 2, ok: 3 };

async function carregar() {
    if (!E.itens.length) $('tbodyItens').innerHTML = linhaCarregando(8);
    try {
        E.itens = (await fetchJSON('/api/itens')).map(i => ({ ...i, ord_sit: ORD_SIT[i.situacao] }));
    } catch (err) {
        showToast(err.message, 'error');
        $('tbodyItens').innerHTML = `<tr><td colspan="8" class="empty">${escapeHTML(err.message)}</td></tr>`;
        return;
    }
    movConfigurar(E.itens, () => recarregarTudo());
    E.sel = new Set([...E.sel].filter(id => E.itens.some(i => i.id === id && i.ativo)));
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
        (!q || normalizar(`${i.codigo} ${i.descricao} ${i.categoria}`).includes(q)));
}

function acoesItem(i) {
    return `${i.ativo ? `<button class="btn btn-sm btn-secondary" data-mov="ENTRADA" data-id="${i.id}" title="Registrar entrada" aria-label="Entrada">${ico('arrow-down')}</button>
        <button class="btn btn-sm btn-secondary" data-mov="SAIDA" data-id="${i.id}" title="Registrar saída" aria-label="Saída">${ico('arrow-up')}</button>` : ''}
        <button class="btn btn-sm btn-secondary" data-ficha="${i.id}" title="Ficha e histórico do item" aria-label="Ficha">${ico('file-text')}</button>
        <button class="btn btn-sm btn-secondary" data-edit="${i.id}" title="Editar cadastro" aria-label="Editar">${ico('pencil')}</button>`;
}

const marcaSel = i => i.ativo
    ? `<input type="checkbox" data-sel="${i.id}" ${E.sel.has(i.id) ? 'checked' : ''} aria-label="Selecionar ${escapeHTML(i.descricao)}">` : '';

function render() {
    const lista = ordenar(filtrar(), E.sort.key, E.sort.dir);
    E.listados = lista;
    $('countBadge').textContent = `${fmtNum(lista.length)} ${lista.length === 1 ? 'item' : 'itens'}`;
    const cards = E.visao === 'cards';
    $('gridCards').hidden = !cards || !lista.length;
    $('wrapLista').hidden = cards && lista.length > 0;
    document.querySelector(`#visao input[value="${E.visao}"]`).checked = true;
    if (!lista.length) {
        $('wrapLista').hidden = false;
        $('tbodyItens').innerHTML = `<tr><td colspan="8" class="empty"><span class="empty-icon">${ico('package', 'ico ico-empty')}</span>
            <h2>${E.itens.length ? 'Nenhum item encontrado' : 'Nenhum item cadastrado'}</h2>
            ${E.itens.length ? 'Ajuste a busca ou os filtros.' : 'Clique em “Novo item” ou importe uma planilha.'}</td></tr>`;
    } else if (cards) {
        $('gridCards').innerHTML = lista.map(i => {
            const alvo = i.estoque_maximo || i.estoque_minimo * 2 || 0;
            const p = alvo ? Math.min(100, (i.saldo / alvo) * 100) : 0;
            const cor = i.situacao === 'zerado' || i.situacao === 'baixo' ? 'var(--red)' : i.situacao === 'excesso' ? 'var(--amber)' : 'var(--green)';
            return `<article class="item-card ${['zerado', 'baixo'].includes(i.situacao) && i.ativo ? 'alerta' : ''}${i.ativo ? '' : ' arquivado'}${E.sel.has(i.id) ? ' selecionado' : ''}">
                <header>
                    <span class="item-card-cod">${escapeHTML(i.codigo)}</span>
                    ${marcaSel(i)}
                </header>
                <a href="#" class="item-card-nome" data-ficha="${i.id}">${escapeHTML(i.descricao)}</a>
                <div class="item-card-cat muted small">${escapeHTML(i.categoria) || 'Sem categoria'}</div>
                <div class="item-card-saldo"><strong>${fmtNum(i.saldo)}</strong> <span class="muted">${escapeHTML(i.unidade)}</span></div>
                ${alvo ? `<div class="kpi-bar" role="progressbar" aria-label="Saldo em relação ao estoque ${i.estoque_maximo ? 'máximo' : 'de referência'}" aria-valuenow="${Math.round(p)}" aria-valuemin="0" aria-valuemax="100"><span style="width:${p}%;background:${cor}"></span></div>` : ''}
                <div class="item-card-info muted small">${i.estoque_minimo ? `Mín. ${fmtNum(i.estoque_minimo)}` : 'Sem mínimo'}${i.estoque_maximo ? ` · Máx. ${fmtNum(i.estoque_maximo)}` : ''}</div>
                <div>${i.ativo ? badgeSituacao(i.situacao) : '<span class="badge neutro">Arquivado</span>'}</div>
                <footer class="acoes">${acoesItem(i)}</footer>
            </article>`;
        }).join('');
    } else {
        $('tbodyItens').innerHTML = lista.map(i => `
        <tr class="${['zerado', 'baixo'].includes(i.situacao) && i.ativo ? 'row-alerta' : ''}${i.ativo ? '' : ' row-arquivado'}">
            <td class="col-sel">${marcaSel(i)}</td>
            <td class="nowrap"><strong>${escapeHTML(i.codigo)}</strong></td>
            <td class="text-left"><a href="#" data-ficha="${i.id}">${escapeHTML(i.descricao)}</a>
                ${!i.ativo ? '<span class="forn-sub">arquivado</span>' : ''}</td>
            <td>${escapeHTML(i.categoria) || '<span class="muted">—</span>'}</td>
            <td class="num nowrap"><strong>${fmtNum(i.saldo)}</strong> <span class="muted small">${escapeHTML(i.unidade)}</span></td>
            <td class="num">${i.estoque_minimo ? fmtNum(i.estoque_minimo) : '<span class="muted">—</span>'}</td>
            <td>${i.ativo ? badgeSituacao(i.situacao) : '<span class="badge neutro">Arquivado</span>'}</td>
            <td class="acoes">${acoesItem(i)}</td>
        </tr>`).join('');
    }
    atualizarSelecao();
}

function atualizarSelecao() {
    const n = E.sel.size;
    $('selBarra').hidden = n === 0;
    $('selQtd').textContent = n;
    const ativosListados = (E.listados || []).filter(i => i.ativo);
    const todos = $('selTodos');
    todos.checked = ativosListados.length > 0 && ativosListados.every(i => E.sel.has(i.id));
    todos.indeterminate = !todos.checked && ativosListados.some(i => E.sel.has(i.id));
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
        $('iCategoria').value = item.categoria || '';
        $('iMin').value = item.estoque_minimo || ''; $('iMax').value = item.estoque_maximo || ''; $('iObs').value = item.observacoes || '';
    } else { $('iUnidade').value = 'UN'; }
    abrirModal('modalItem');
}

async function salvarItem(ev) {
    ev.preventDefault();
    const corpo = {
        codigo: $('iCodigo').value, descricao: $('iDescricao').value, unidade: $('iUnidade').value, categoria: $('iCategoria').value,
        estoque_minimo: $('iMin').value, estoque_maximo: $('iMax').value, observacoes: $('iObs').value,
    };
    if (!E.editando) { corpo.saldo_inicial = $('iSaldo').value; }
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
                    ${i.estoque_minimo ? chip('Mínimo', fmtNum(i.estoque_minimo)) : ''}
                    ${i.estoque_maximo ? chip('Máximo', fmtNum(i.estoque_maximo)) : ''}
                    ${i.categoria ? chip('Categoria', escapeHTML(i.categoria)) : ''}
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
                <thead><tr><th>Data</th><th>Tipo</th><th>Quantidade</th><th>Saldo após</th><th>Observações</th><th>Usuário</th></tr></thead>
                <tbody>${d.movimentos.length ? d.movimentos.map(m => `
                    <tr><td class="nowrap">${dataBR(m.data)}</td><td>${badgeTipo(m.tipo)}</td>
                    <td class="num nowrap">${qtdeSinal(m.qtde, i.unidade)}</td><td class="num">${fmtNum(m.saldo_apos)}</td>
                    <td>${escapeHTML(m.observacoes) || '<span class="muted">—</span>'}</td><td>${escapeHTML(m.usuario)}</td></tr>`).join('')
                    : `<tr><td colspan="6" class="empty">Sem movimentações ainda.</td></tr>`}</tbody>
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

// ---------- Baixa em lote ----------
const LOTE = { linhas: [] };   // [{id, qtde}]

function abrirLote(ids = []) {
    const ativos = E.itens.filter(i => i.ativo);
    if (!ativos.length) { showToast('Cadastre um item antes de dar baixa.', 'error'); return; }
    LOTE.linhas = ids.map(id => ({ id, qtde: '' }));
    $('formLote').reset();
    $('loteErro').hidden = true;
    $('loteData').value = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    $('loteData').max = $('loteData').value;
    renderLote();
    abrirModal('modalLote');
}

function renderLote() {
    const usados = new Set(LOTE.linhas.map(l => l.id));
    const disp = E.itens.filter(i => i.ativo && !usados.has(i.id)).sort((a, b) => a.descricao.localeCompare(b.descricao, 'pt-BR'));
    $('loteAdd').innerHTML = '<option value="">Adicionar material…</option>' + disp.map(i =>
        `<option value="${i.id}">${escapeHTML(i.codigo)} — ${escapeHTML(i.descricao)} (${fmtNum(i.saldo)} ${escapeHTML(i.unidade)})</option>`).join('');
    $('loteLinhas').innerHTML = LOTE.linhas.length ? LOTE.linhas.map((l, k) => {
        const i = E.itens.find(x => x.id === l.id);
        return `<tr>
            <td class="text-left"><strong>${escapeHTML(i.descricao)}</strong><span class="forn-sub">${escapeHTML(i.codigo)}</span></td>
            <td class="num nowrap">${fmtNum(i.saldo)} <span class="muted small">${escapeHTML(i.unidade)}</span></td>
            <td class="num"><input class="input input-qtde" inputmode="decimal" data-lq="${k}" value="${escapeHTML(l.qtde)}" placeholder="0" aria-label="Quantidade de ${escapeHTML(i.descricao)}"></td>
            <td class="acoes"><button type="button" class="btn btn-sm btn-ghost" data-lrm="${k}" title="Tirar da lista" aria-label="Tirar da lista">${ico('trash')}</button></td>
        </tr>`;
    }).join('') : `<tr><td colspan="4" class="empty">Escolha os materiais acima ou marque-os na lista de itens.</td></tr>`;
}

$('loteAddBtn').addEventListener('click', () => {
    const id = +$('loteAdd').value;
    if (!id) return;
    LOTE.linhas.push({ id, qtde: '' });
    renderLote();
    const ult = $('loteLinhas').querySelector('tr:last-child [data-lq]');
    if (ult) ult.focus();
});
$('loteLinhas').addEventListener('input', ev => {
    const q = ev.target.closest('[data-lq]');
    if (q) LOTE.linhas[+q.dataset.lq].qtde = q.value;
});
$('loteLinhas').addEventListener('click', ev => {
    const b = ev.target.closest('[data-lrm]');
    if (!b) return;
    LOTE.linhas.splice(+b.dataset.lrm, 1);
    renderLote();
});
$('loteCancelar').addEventListener('click', () => fecharModal('modalLote'));
$('formLote').addEventListener('submit', async ev => {
    ev.preventDefault();
    const err = $('loteErro');
    const mostrar = (msg, lista = []) => {
        err.firstElementChild.innerHTML = escapeHTML(msg) + (lista.length ? `<ul class="lista-erros">${lista.map(e => `<li>${escapeHTML(e)}</li>`).join('')}</ul>` : '');
        err.hidden = false;
    };
    if (!LOTE.linhas.length) { mostrar('Escolha ao menos um material.'); return; }
    const vazios = LOTE.linhas.filter(l => !(parseNumBR(l.qtde) > 0));
    if (vazios.length) { mostrar('Informe a quantidade de todos os materiais da lista (ou tire da lista os que não vão sair).'); return; }
    const btn = $('loteSalvar');
    btn.disabled = true;
    try {
        const r = await enviarJSON('/api/movimentos/lote', 'POST', {
            data: $('loteData').value, observacoes: $('loteObs').value,
            itens: LOTE.linhas.map(l => ({ item_id: l.id, qtde: parseNumBR(l.qtde) })),
        });
        if (!r.ok) { mostrar(r.error, r.erros || []); return; }
        fecharModal('modalLote');
        E.sel.clear();
        showToast(`${fmtNum(r.lancadas)} saída(s) lançada(s).`, 'success');
        await recarregarTudo();
        atualizarAlertas();
    } catch (e) { mostrar(e.message); }
    finally { btn.disabled = false; }
});
$('btnLote').addEventListener('click', () => abrirLote([...E.sel]));
$('btnBaixaSel').addEventListener('click', () => abrirLote([...E.sel]));
$('btnLimparSel').addEventListener('click', () => { E.sel.clear(); render(); });

// ---------- Seleção e modo de exibição ----------
function alternarSel(id, marcado) {
    if (marcado) E.sel.add(id); else E.sel.delete(id);
    render();
}
document.addEventListener('change', ev => {
    const c = ev.target.closest('[data-sel]');
    if (c) alternarSel(+c.dataset.sel, c.checked);
});
$('selTodos').addEventListener('change', () => {
    (E.listados || []).filter(i => i.ativo).forEach(i => { if ($('selTodos').checked) E.sel.add(i.id); else E.sel.delete(i.id); });
    render();
});
document.querySelectorAll('#visao input').forEach(r => r.addEventListener('change', () => {
    E.visao = r.value;
    try { localStorage.setItem('estoque_visao', E.visao); } catch { /* sem storage */ }
    render();
}));

// ---------- Eventos ----------
function cliqueItem(ev) {
    const b = ev.target.closest('[data-mov],[data-ficha],[data-edit]');
    if (!b) return;
    ev.preventDefault();
    const id = +(b.dataset.id || b.dataset.ficha || b.dataset.edit);
    if (b.dataset.mov) abrirMov(b.dataset.mov, id);
    else if (b.dataset.ficha) abrirFicha(id);
    else abrirItem(E.itens.find(i => i.id === id));
}
$('gridCards').addEventListener('click', cliqueItem);
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
    if (p.get('situacao')) $('fSituacao').value = ['zerado', 'baixo', 'repor'].includes(p.get('situacao')) ? p.get('situacao') : '';
    await carregar();
    if (p.get('novo')) abrirItem();
    if (p.get('lote')) abrirLote();
    if (p.get('id')) abrirFicha(+p.get('id'));
})();
