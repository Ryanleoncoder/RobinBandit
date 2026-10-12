const catalogosAbertos = new Map();

function mostrarCatalogo(caixa, quem, dados, selecionados, acrescentar) {
  catalogosAbertos.set(quem, dados);
  const modelos = (dados.models || dados.modelos || []).map(m => typeof m === 'string' ? { id: m } : m)
    .filter(m => (m.id || m.nome) && m.selectable !== false);
  const bloco = document.createElement('div'); bloco.className = 'catalogo-aberto';
  const busca = document.createElement('input'); busca.type = 'search';
  busca.placeholder = L('Buscar modelo, modalidade ou preço…', 'Search model, modality or price…');
  busca.setAttribute('aria-label', busca.placeholder);
  const info = document.createElement('p'); info.className = 'catalogo-contagem'; info.setAttribute('role', 'status');
  const lista = document.createElement('div'); lista.className = 'catalogo-lista';
  bloco.append(busca, info, lista); caixa.replaceChildren(bloco);
  (dados.warnings || []).forEach(aviso => { const p = document.createElement('p'); p.className = 'dica'; p.textContent = aviso; bloco.prepend(p); });
  function desenhar() {
    const termo = normalizarBusca(busca.value);
    const achados = modelos.filter(m => normalizarBusca([m.id, m.nome, m.name, ...(m.roles || []), m.price_class].join(' ')).includes(termo));
    info.textContent = Math.min(200, achados.length) + L(' de ', ' of ') + achados.length + L(' modelos. Clique para acrescentar à ordem.', ' models. Click to add to the order.');
    lista.replaceChildren();
    achados.slice(0, 200).forEach(m => {
      const id = m.id || m.nome;
      const botao = document.createElement('button'); botao.type = 'button'; botao.disabled = selecionados.includes(id);
      const nome = document.createElement('span'); nome.className = 'nome-modelo'; nome.textContent = id;
      const preco = document.createElement('span'); preco.className = 'selo';
      preco.textContent = m.price_class === 'free' ? L('grátis', 'free') : m.price_class === 'paid' ? L('pago', 'paid') : L('preço não informado', 'price unknown');
      const estado = document.createElement('span'); estado.className = 'selo'; estado.textContent = botao.disabled ? L('adicionado', 'added') : L('adicionar', 'add');
      botao.append(nome, preco, estado);
      botao.addEventListener('click', async () => { botao.disabled = true; await acrescentar(id); });
      lista.append(botao);
    });
  }
  busca.addEventListener('input', desenhar); desenhar();
}
