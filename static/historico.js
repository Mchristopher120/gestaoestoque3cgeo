// Histórico de alterações (auditoria)
let HIST = [];
const ACAO = {
    CRIAR: ['plus', 'Cadastrou', 'info'], EDITAR: ['pencil', 'Editou', 'neutro'], EXCLUIR: ['trash', 'Excluiu', 'critico'],
    ENTRADA: ['arrow-down', 'Entrada', 'ok'], SAIDA: ['arrow-up', 'Saída', 'atencao'], AJUSTE: ['adjustments', 'Ajuste', 'info'],
    ESTORNAR: ['arrow-back-up', 'Estorno', 'critico'], IMPORTAR: ['file-upload', 'Importou', 'info'],
    EXPORTAR: ['download', 'Exportou', 'neutro'], LOGIN: ['key', 'Entrou', 'neutro'],
};

async function carregar() {
    $('tbodyHist').innerHTML = linhaCarregando(4);
    try { HIST = await fetchJSON('/api/historico?limite=1000'); }
    catch (err) { showToast(err.message, 'error'); $('tbodyHist').innerHTML = `<tr><td colspan="4" class="empty">${escapeHTML(err.message)}</td></tr>`; return; }
    const usuarios = [...new Set(HIST.map(h => h.usuario).filter(Boolean))].sort();
    $('hUsuario').innerHTML = '<option value="">Todos os usuários</option>' + usuarios.map(u => `<option>${escapeHTML(u)}</option>`).join('');
    render();
}

function render() {
    const q = normalizar($('hBusca').value.trim()), acao = $('hAcao').value, usr = $('hUsuario').value;
    const lista = HIST.filter(h => (!acao || h.acao === acao) && (!usr || h.usuario === usr) &&
        (!q || normalizar(`${h.descricao} ${h.usuario}`).includes(q)));
    $('tbodyHist').innerHTML = lista.length ? lista.map(h => {
        const [icone, rot, cls] = ACAO[h.acao] || ['history', h.acao, 'neutro'];
        return `<tr><td class="nowrap">${dataBR(h.quando)}</td><td>${escapeHTML(h.usuario)}</td>
            <td><span class="badge ${cls}">${ico(icone)} ${rot}</span></td>
            <td class="text-left">${h.item_id ? `<a href="/estoque?id=${h.item_id}">${escapeHTML(h.descricao)}</a>` : escapeHTML(h.descricao)}</td></tr>`;
    }).join('') : `<tr><td colspan="4" class="empty">Nenhum registro encontrado.</td></tr>`;
}
['hBusca', 'hAcao', 'hUsuario'].forEach(id => $(id).addEventListener('input', render));
carregar();
