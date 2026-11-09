// Tema claro / escuro. Carregado no <head> para aplicar antes de desenhar a página
// (evita o "flash" branco). Preferência: 'auto' (segue o sistema), 'dark' ou 'light'.
(function () {
    var CHAVE = 'estoque-tema';
    var midia = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

    var memoria = null; // usado se o navegador bloquear o armazenamento
    function lerPreferencia() {
        if (memoria) return memoria;
        try { return localStorage.getItem(CHAVE) || 'auto'; } catch (e) { return 'auto'; }
    }
    function salvarPreferencia(v) {
        memoria = v;
        try { localStorage.setItem(CHAVE, v); } catch (e) { /* vale só nesta página */ }
    }
    function aplicar(pref) {
        var escuro = pref === 'dark' || (pref === 'auto' && midia && midia.matches);
        document.documentElement.setAttribute('data-theme', escuro ? 'dark' : 'light');
        document.documentElement.setAttribute('data-tema-pref', pref);
        var btn = document.getElementById('btnTema');
        if (btn) {
            // O ícone certo aparece via CSS (data-tema-pref); aqui só o texto e a dica
            var info = {
                auto: ['Automático', 'Tema automático (segue o sistema). Clique para escuro.'],
                dark: ['Escuro', 'Tema escuro. Clique para claro.'],
                light: ['Claro', 'Tema claro. Clique para automático.'],
            }[pref];
            var rotulo = btn.querySelector('.tema-rotulo');
            if (rotulo) rotulo.textContent = info[0];
            btn.title = info[1];
            btn.setAttribute('aria-label', info[1]);
        }
    }

    var pref = lerPreferencia();
    aplicar(pref);

    if (midia) {
        var mudou = function () { if (lerPreferencia() === 'auto') aplicar('auto'); };
        if (midia.addEventListener) midia.addEventListener('change', mudou); else if (midia.addListener) midia.addListener(mudou);
    }

    document.addEventListener('DOMContentLoaded', function () {
        aplicar(lerPreferencia());
        var btn = document.getElementById('btnTema');
        if (!btn) return;
        btn.addEventListener('click', function () {
            var proximo = { auto: 'dark', dark: 'light', light: 'auto' }[lerPreferencia()] || 'auto';
            salvarPreferencia(proximo);
            aplicar(proximo);
        });
    });
})();
