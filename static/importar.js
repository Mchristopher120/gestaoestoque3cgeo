// Importar planilha de itens
const inp = $('arquivo'), dz = $('dropzone');

function escolher(arq) {
    $('nomeArquivo').textContent = arq ? arq.name : 'Escolha ou arraste a planilha aqui';
    $('btnEnviar').disabled = !arq;
}
inp.addEventListener('change', () => escolher(inp.files[0]));
['dragenter', 'dragover'].forEach(e => dz.addEventListener(e, ev => { ev.preventDefault(); dz.classList.add('arrastando'); }));
['dragleave', 'drop'].forEach(e => dz.addEventListener(e, ev => { ev.preventDefault(); dz.classList.remove('arrastando'); }));
dz.addEventListener('drop', ev => { if (ev.dataTransfer.files.length) { inp.files = ev.dataTransfer.files; escolher(inp.files[0]); } });

$('formImp').addEventListener('submit', async ev => {
    ev.preventDefault();
    if (!inp.files[0]) return;
    const fd = new FormData();
    fd.append('arquivo', inp.files[0]);
    const btn = $('btnEnviar');
    btn.disabled = true;
    $('resultado').innerHTML = `<div class="import-msg info"><span class="spinner"></span><div>Importando…</div></div>`;
    try {
        const r = await fetchJSON('/api/importar', { method: 'POST', body: fd });
        if (!r.ok) { $('resultado').innerHTML = `<div class="import-msg erro">${ico('alert-triangle')}<div><strong>Não foi possível importar</strong>${escapeHTML(r.error)}</div></div>`; return; }
        const temErro = r.total_erros > 0;
        $('resultado').innerHTML = `
            <div class="import-msg ${temErro ? 'aviso' : 'ok'}">${ico(temErro ? 'alert-triangle' : 'circle-check')}
                <div><strong>${fmtNum(r.criados)} item(ns) novo(s) e ${fmtNum(r.atualizados)} atualizado(s)</strong>
                ${temErro ? `${fmtNum(r.total_erros)} linha(s) com problema foram ignoradas:<ul class="lista-erros">${r.erros.map(e => `<li>${escapeHTML(e)}</li>`).join('')}</ul>` : 'Tudo certo.'}
                </div>
                <a class="btn btn-secondary btn-sm" href="/estoque">Ver estoque</a>
            </div>`;
        inp.value = ''; escolher(null);
        atualizarAlertas();
    } catch (err) {
        $('resultado').innerHTML = `<div class="import-msg erro">${ico('alert-triangle')}<div><strong>Erro</strong>${escapeHTML(err.message)}</div></div>`;
    } finally { btn.disabled = !inp.files[0]; }
});


// Saídas em lote
const inpSai = $('arquivoSai'), dzSai = $('dropzoneSai');

function escolherSai(arq) {
    $('nomeArquivoSai').textContent = arq ? arq.name : 'Escolha ou arraste a planilha de saídas aqui';
    $('btnEnviarSai').disabled = !arq;
}
inpSai.addEventListener('change', () => escolherSai(inpSai.files[0]));
['dragenter', 'dragover'].forEach(e => dzSai.addEventListener(e, ev => { ev.preventDefault(); dzSai.classList.add('arrastando'); }));
['dragleave', 'drop'].forEach(e => dzSai.addEventListener(e, ev => { ev.preventDefault(); dzSai.classList.remove('arrastando'); }));
dzSai.addEventListener('drop', ev => { if (ev.dataTransfer.files.length) { inpSai.files = ev.dataTransfer.files; escolherSai(inpSai.files[0]); } });

$('formSai').addEventListener('submit', async ev => {
    ev.preventDefault();
    if (!inpSai.files[0]) return;
    const fd = new FormData();
    fd.append('arquivo', inpSai.files[0]);
    const btn = $('btnEnviarSai');
    btn.disabled = true;
    $('resultadoSai').innerHTML = `<div class="import-msg info"><span class="spinner"></span><div>Lançando saídas…</div></div>`;
    try {
        const r = await fetchJSON('/api/importar/saidas', { method: 'POST', body: fd });
        if (!r.ok) { $('resultadoSai').innerHTML = `<div class="import-msg erro">${ico('alert-triangle')}<div><strong>Não foi possível lançar</strong>${escapeHTML(r.error)}</div></div>`; return; }
        const temErro = r.total_erros > 0;
        $('resultadoSai').innerHTML = `
            <div class="import-msg ${temErro ? 'aviso' : 'ok'}">${ico(temErro ? 'alert-triangle' : 'circle-check')}
                <div><strong>${fmtNum(r.lancadas)} saída(s) lançada(s)</strong>
                ${temErro ? `${fmtNum(r.total_erros)} linha(s) ignorada(s):<ul class="lista-erros">${r.erros.map(e => `<li>${escapeHTML(e)}</li>`).join('')}</ul>` : 'Tudo certo.'}
                </div>
                <a class="btn btn-secondary btn-sm" href="/movimentacoes">Ver movimentações</a>
            </div>`;
        inpSai.value = ''; escolherSai(null);
        atualizarAlertas();
    } catch (err) {
        $('resultadoSai').innerHTML = `<div class="import-msg erro">${ico('alert-triangle')}<div><strong>Erro</strong>${escapeHTML(err.message)}</div></div>`;
    } finally { btn.disabled = !inpSai.files[0]; }
});
