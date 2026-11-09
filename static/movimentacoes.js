// Tela Movimentações
const M = { movs: [], sort: { key: null, dir: 1 } };

async function carregar() {
    if (!M.movs.length) $('tbodyMov').innerHTML = linhaCarregando(8);
    try {
        const [movs, itens] = await Promise.all([fetchJSON('/api/movimentos?limite=1000'), fetchJSON('/api/itens')]);
        M.movs = movs;
        movConfigurar(itens, () => carregar());
    } catch (err) {
        showToast(err.message, 'error');
        $('tbodyMov').innerHTML = `<tr><td colspan="8" class="empty">${escapeHTML(err.message)}</td></tr>`;
        return;
    }
    render();
}

function render() {
    const q = normalizar($('fBusca').value.trim()), tipo = $('fTipo').value, de = $('fDe').value, ate = $('fAte').value;
    const lista = ordenar(M.movs.filter(m =>
        (!tipo || m.tipo === tipo) && (!de || m.data >= de) && (!ate || m.data <= ate) &&
        (!q || normalizar(`${m.codigo} ${m.descricao} ${m.documento} ${m.contraparte} ${m.usuario}`).includes(q))), M.sort.key, M.sort.dir);
    $('countBadge').textContent = `${fmtNum(lista.length)} ${lista.length === 1 ? 'registro' : 'registros'}`;
    $('tbodyMov').innerHTML = lista.length ? lista.map(m => `
        <tr>
            <td class="nowrap">${dataBR(m.data)}</td>
            <td>${badgeTipo(m.tipo)}</td>
            <td class="text-left"><a href="/estoque?id=${m.item_id}">${escapeHTML(m.descricao)}</a><span class="forn-sub">${escapeHTML(m.codigo)}</span></td>
            <td class="num nowrap">${qtdeSinal(m.qtde, m.unidade)}</td>
            <td>${escapeHTML(m.documento) || '<span class="muted">—</span>'}</td>
            <td>${escapeHTML(m.contraparte) || '<span class="muted">—</span>'}</td>
            <td>${escapeHTML(m.usuario)}</td>
            <td class="acoes"><button class="btn btn-sm btn-danger" data-estornar="${m.id}" title="Estornar este lançamento" aria-label="Estornar">${ico('arrow-back-up')}</button></td>
        </tr>`).join('')
        : `<tr><td colspan="8" class="empty"><span class="empty-icon">${ico('arrows-exchange', 'ico ico-empty')}</span>Nenhuma movimentação encontrada.</td></tr>`;
}

$('tbodyMov').addEventListener('click', async ev => {
    const b = ev.target.closest('[data-estornar]');
    if (!b) return;
    const m = M.movs.find(x => x.id === +b.dataset.estornar);
    if (!confirm(`Estornar ${TIPO_MOV[m.tipo].rot.toLowerCase()} de ${fmtNum(Math.abs(m.qtde))} ${m.unidade} — ${m.descricao} (${dataBR(m.data)})?\nO lançamento sai do saldo e fica registrado no histórico.`)) return;
    try {
        const r = await enviarJSON(`/api/movimentos/${m.id}`, 'DELETE');
        if (!r.ok) { showToast(r.error, 'error'); return; }
        showToast('Lançamento estornado.', 'success');
        carregar(); atualizarAlertas();
    } catch (err) { showToast(err.message, 'error'); }
});
$('btnEntrada').addEventListener('click', () => abrirMov('ENTRADA'));
$('btnSaida').addEventListener('click', () => abrirMov('SAIDA'));
['fBusca', 'fTipo', 'fDe', 'fAte'].forEach(id => $(id).addEventListener('input', render));
ativarOrdenacao($('tblMov'), M.sort, render);
carregar();
