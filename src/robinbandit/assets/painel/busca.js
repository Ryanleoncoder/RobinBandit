let consultaProvedor = '';

function textoSeguro(valor) {
  return String(valor || '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

function normalizarBusca(valor) {
  return String(valor || '').normalize('NFKD').replace(/\p{M}/gu, '').toLocaleLowerCase();
}

function enderecoSeguro(valor) {
  try { const url = new URL(valor); return ['https:', 'http:'].includes(url.protocol) ? url.href : ''; }
  catch { return ''; }
}

function marcarBusca(elemento, item, naCadeia = true) {
  if (!elemento) return;
  elemento.dataset.busca = normalizarBusca([item.nome, item.label, item.id, item.provider, item.key_env,
    ...(item.modelos || item.models || [])].filter(Boolean).join(' '));
  elemento.dataset.naCadeia = naCadeia ? '1' : '0';
}

function aplicarBusca() {
  const termo = normalizarBusca(consultaProvedor.trim());
  const fixo = config && ['fixed', 'round_robin'].includes(config.estrategia);
  const mostraOrdem = fixo && !provedoresDeTodos;
  const tipos = [
    ['provedores', mostraOrdem ? '#ordem-cadeia .lista-cadeia li' : '#tiers .grade > div', provedoresDeTodos],
    ['modelos', '#modelos .provlinha', modelosDeTodos],
    ['credenciais', '#credenciais .cred', contasDeTodos],
  ];
  const tela = document.querySelector('nav [aria-current="page"]')?.dataset.tela;
  $('buscar-provedor').placeholder = tela === 'credenciais'
    ? L('Buscar provedor, conta ou variável…', 'Search provider, account or variable…')
    : L('Buscar provedor ou modelo…', 'Search provider or model…');
  $('busca-provedor').hidden = !tipos.some(([nome]) => nome === tela);
  $('limpar-busca').hidden = !termo;
  for (const [nome, seletor, todos] of tipos) {
    const itens = Array.from(document.querySelectorAll(seletor));
    let visiveis = 0;
    itens.forEach(el => {
      el.hidden = termo ? !el.dataset.busca?.includes(termo) : !todos && el.dataset.naCadeia !== '1';
      if (!el.hidden) visiveis++;
    });
    const grupos = nome === 'provedores' ? '#tiers .faixa' : nome === 'credenciais' ? '#credenciais .grupo-cred' : '';
    if (grupos) document.querySelectorAll(grupos).forEach(g => {
      g.hidden = !Array.from(g.querySelectorAll(nome === 'provedores' ? '.grade > div' : '.cred')).some(el => !el.hidden);
    });
    if (nome === 'provedores') {
      $('tiers').hidden = mostraOrdem;
      $('ordem-cadeia').hidden = !mostraOrdem;
      $('nota-fallback').hidden = $('tiers').hidden;
    }
    if (tela === nome) {
      $('busca-contagem').textContent = visiveis + L(' de ', ' of ') + itens.length + L(' resultados', ' results');
      $('busca-vazia').hidden = visiveis > 0;
      $('busca-vazia').textContent = nome === 'provedores' && mostraOrdem
        ? L('Nenhum provedor nesta ordem. Consulte o catálogo completo para incluir outro.', 'No provider in this order. Open the full catalog to include another.')
        : termo
        ? L('Nenhum resultado. Tente o nome do provedor, da conta, do modelo ou da variável.', 'No results. Try a provider, account, model or variable name.')
        : L('Nada neste filtro. Veja o catálogo completo ou use a busca.', 'Nothing in this filter. Open the full catalog or search.');
    }
  }
}

function focarProvedor(nome, tela = 'credenciais') {
  consultaProvedor = nome;
  $('buscar-provedor').value = nome;
  trocarTela(tela);
  aplicarBusca();
  $('buscar-provedor').focus();
}

function inicializarBusca() {
  $('buscar-provedor').placeholder = L('Provedor, conta, modelo ou variável…', 'Provider, account, model or variable…');
  $('buscar-provedor').addEventListener('input', e => {
    consultaProvedor = e.target.value;
    aplicarBusca();
  });
  $('limpar-busca').textContent = L('Limpar', 'Clear');
  $('limpar-busca').addEventListener('click', () => {
    consultaProvedor = ''; $('buscar-provedor').value = ''; aplicarBusca(); $('buscar-provedor').focus();
  });
}
