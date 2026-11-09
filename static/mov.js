// Janela de movimentação (entrada / saída / ajuste) — compartilhada por Estoque e Movimentações.
const MOV = { itens: [], aoSalvar: null };

function movConfigurar(itens, aoSalvar) {
    MOV.itens = itens.filter(i => i.ativo).sort((a, b) => a.descricao.localeCompare(b.descricao, 'pt-BR'));
    MOV.aoSalvar = aoSalvar;
}

const movTipoAtual = () => document.querySelector('#movTipo input:checked').value;
const movItemAtual = () => MOV.itens.find(i => String(i.id) === $('movItem').value);

function abrirMov(tipo = 'ENTRADA', itemId = null) {
    if (!MOV.itens.length) { showToast('Cadastre um item antes de movimentar.', 'error'); return; }
    $('formMov').reset();
    $('movErro').hidden = true;
    $('movItem').innerHTML = '<option value="">Escolha o item…</option>' + MOV.itens.map(i =>
        `<option value="${i.id}">${escapeHTML(i.codigo)} — ${escapeHTML(i.descricao)}</option>`).join('');
    if (itemId) $('movItem').value = String(itemId);
    document.querySelector(`#movTipo input[value="${tipo}"]`).checked = true;
    $('movData').value = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    $('movData').max = $('movData').value;
    movAtualizar();
    abrirModal('modalMov');
    if (itemId) setTimeout(() => ($(tipo === 'AJUSTE' ? 'movContado' : 'movQtde')).focus(), 60);
}

function movAtualizar() {
    const t = movTipoAtual(), it = movItemAtual();
    $('movTitulo').textContent = { ENTRADA: 'Registrar entrada', SAIDA: 'Registrar saída', AJUSTE: 'Ajuste de inventário' }[t];
    $('gQtde').hidden = t === 'AJUSTE';
    $('gContado').hidden = t !== 'AJUSTE';
    $('lblContra').parentElement.hidden = t === 'AJUSTE';
    $('lblDoc').textContent = t === 'ENTRADA' ? 'Nota fiscal / documento' : t === 'SAIDA' ? 'Requisição / documento' : 'Documento (opcional)';
    $('lblContra').textContent = t === 'ENTRADA' ? 'Fornecedor' : 'Destino (setor ou pessoa)';
    $('lblObs').textContent = t === 'AJUSTE' ? 'Motivo do ajuste (obrigatório)' : 'Observações';
    $('movSalvar').textContent = t === 'AJUSTE' ? 'Ajustar saldo' : 'Registrar';
    $('movSaldoInfo').innerHTML = it
        ? `Saldo atual: <strong>${fmtNum(it.saldo)} ${escapeHTML(it.unidade)}</strong>` +
          (it.localizacao ? ` · ${escapeHTML(it.localizacao)}` : '')
        : '';
    movResumo();
}

function movResumo() {
    const t = movTipoAtual(), it = movItemAtual(), box = $('movResumo');
    if (!it) { box.hidden = true; return; }
    let html = '';
    if (t === 'ENTRADA') {
        const q = parseNumBR($('movQtde').value);
        if (q > 0) html = `Novo saldo: <strong>${fmtNum(it.saldo + q)} ${escapeHTML(it.unidade)}</strong>`;
    } else if (t === 'SAIDA') {
        const q = parseNumBR($('movQtde').value);
        if (q > 0) html = q > it.saldo
            ? `<span class="text-red">Saldo insuficiente (há ${fmtNum(it.saldo)} ${escapeHTML(it.unidade)}).</span>`
            : `Novo saldo: <strong>${fmtNum(it.saldo - q)} ${escapeHTML(it.unidade)}</strong>`;
    } else if ($('movContado').value.trim() !== '') {
        const dif = parseNumBR($('movContado').value) - it.saldo;
        html = Math.abs(dif) < 1e-9 ? 'O saldo contado confere com o sistema.'
            : `Diferença: <strong class="${dif > 0 ? 'text-green' : 'text-red'}">${dif > 0 ? '+' : '−'}${fmtNum(Math.abs(dif))} ${escapeHTML(it.unidade)}</strong>`;
    }
    box.innerHTML = html;
    box.hidden = !html;
}

async function movSalvar(ev) {
    ev.preventDefault();
    const t = movTipoAtual();
    const corpo = {
        tipo: t, item_id: $('movItem').value, data: $('movData').value,
        documento: $('movDoc').value, contraparte: t === 'AJUSTE' ? '' : $('movContra').value, observacoes: $('movObs').value,
    };
    if (t === 'AJUSTE') corpo.saldo_contado = $('movContado').value;
    else corpo.qtde = $('movQtde').value;
    const btn = $('movSalvar');
    btn.disabled = true;
    try {
        const r = await enviarJSON('/api/movimentos', 'POST', corpo);
        if (!r.ok) { const e = $('movErro'); e.firstElementChild.textContent = r.error; e.hidden = false; return; }
        fecharModal('modalMov');
        showToast(`${TIPO_MOV[t].rot} registrada.`, 'success');
        if (MOV.aoSalvar) MOV.aoSalvar(r.item);
        atualizarAlertas();
    } catch (err) {
        const e = $('movErro'); e.firstElementChild.textContent = err.message; e.hidden = false;
    } finally { btn.disabled = false; }
}

$('formMov').addEventListener('submit', movSalvar);
$('movCancelar').addEventListener('click', () => fecharModal('modalMov'));
document.querySelectorAll('#movTipo input').forEach(r => r.addEventListener('change', movAtualizar));
$('movItem').addEventListener('change', movAtualizar);
['movQtde', 'movContado'].forEach(id => $(id).addEventListener('input', movResumo));
