function montarLogin(raiz) {
  const provedor = raiz.dataset.loginProvedor;
  const direto = raiz.dataset.loginTipo === 'chatgpt_oauth' || raiz.dataset.loginDireto === '1';
  const caminho = 'login/' + encodeURIComponent(provedor);
  let tentativa = null;
  let timer = null;
  let lendo = false;
  const texto = document.createElement('p');
  texto.className = 'cli';
  const botoes = document.createElement('div');
  botoes.className = 'login-acoes';
  raiz.append(texto, botoes);
  async function api(url, method = 'GET', body) {
    const resposta = await fetch(url, {
      method, headers: { 'Content-Type': 'application/json', 'X-RobinBandit-Login': '1' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: AbortSignal.timeout(25000)
    });
    const dado = await resposta.json();
    if (!resposta.ok) throw new Error(dado.detail || L('Não foi possível conectar.', 'Could not connect.'));
    return dado;
  }
  function parar() { clearTimeout(timer); timer = null; }
  function botao(rotulo, acao) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'acao'; b.textContent = rotulo;
    b.onclick = async () => {
      b.disabled = true;
      try { await acao(); } catch (e) { texto.textContent = e.message; }
      finally { b.disabled = false; }
    };
    botoes.append(b);
    return b;
  }
  async function acompanhar() {
    if (!raiz.isConnected || !tentativa) { parar(); return; }
    try {
      const estado = await api('login/tentativas/' + encodeURIComponent(tentativa));
      texto.textContent = estado.detalhe || ({ aguardando: L('Conclua o login no navegador aberto.', 'Finish signing in in the browser.'),
        validando: L('Validando a autorização.', 'Validating authorization.'), conectado: L('Conta conectada.', 'Account connected.'),
        cancelado: L('Login cancelado.', 'Sign-in cancelled.'), expirado: L('Login expirou. Tente novamente.', 'Sign-in expired. Try again.'),
        falhou: L('Login não foi concluído. Use o comando oficial no terminal ou tente novamente.', 'Sign-in did not complete. Use the official terminal command or try again.') })[estado.estado];
      if (['aguardando', 'validando'].includes(estado.estado)) timer = setTimeout(acompanhar, 2000);
      else {
        const detalhe = texto.textContent;
        tentativa = null; await status();
        if (!estado.configurada) texto.textContent = detalhe;
      }
    } catch (e) {
      parar(); texto.textContent = e.message;
      botoes.replaceChildren();
      botao(L('Verificar novamente', 'Check again'), acompanhar);
      botao(L('Cancelar', 'Cancel'), async () => { await api('login/tentativas/' + tentativa, 'DELETE'); tentativa = null; await status(); });
    }
  }
  async function iniciar(conta = '', metodo = '') {
    parar();
    const login = await api(caminho, 'POST', { conta, metodo });
    tentativa = login.id;
    botoes.replaceChildren();
    botao(L('Cancelar login', 'Cancel sign-in'), async () => {
      await api('login/tentativas/' + encodeURIComponent(tentativa), 'DELETE');
      tentativa = null; parar(); await status();
    });
    await acompanhar();
  }
  async function status() {
    if (lendo || !raiz.isConnected) return;
    lendo = true;
    try {
      const s = await api(caminho);
      botoes.replaceChildren();
      if (s.tentativa) {
        tentativa = s.tentativa;
        botao(L('Cancelar login', 'Cancel sign-in'), async () => {
          await api('login/tentativas/' + tentativa, 'DELETE'); tentativa = null; parar(); await status();
        });
        timer = setTimeout(acompanhar, 0);
        return;
      }
      texto.textContent = s.configurada ? (s.metodo === 'cli' ? L('ChatGPT conectado pelo Codex CLI.', 'ChatGPT connected through Codex CLI.') : L('Conta conectada.', 'Account connected.'))
        : direto ? L('Entre no navegador com um plano elegível. Não precisa instalar Codex.', 'Sign in in your browser with an eligible plan. No Codex installation needed.')
        : s.instalado ? L('CLI instalado, falta entrar na conta.', 'CLI installed. Sign in to your account.')
        : L('Instale o CLI oficial. Desktop não é obrigatório.', 'Install the official CLI. Desktop is not required.');
      if (direto) {
        if (!s.disponivel) texto.textContent = L('Instale robinbandit[auth] na pasta local para habilitar o login direto.', 'Install robinbandit[auth] from the local folder to enable direct sign-in.');
        else botao(L('Continuar com ChatGPT', 'Continue with ChatGPT'), () => iniciar());
        if (raiz.dataset.loginDireto === '1') {
          if (s.instalado) botao(L('Usar Codex CLI', 'Use Codex CLI'), () => iniciar('', 'cli'));
          else if (s.instalacao_url) {
            const link = document.createElement('a');
            link.href = s.instalacao_url; link.target = '_blank'; link.rel = 'noopener noreferrer';
            link.textContent = L('Alternativa: instalar Codex CLI', 'Alternative: install Codex CLI'); botoes.append(link);
          }
        }
        for (const conta of s.contas || []) {
          const ativa = s.ativa === conta.id && s.metodo !== 'cli';
          const label = conta.label + (conta.email ? ' (' + conta.email + ')' : '');
          botao(label + (ativa ? L(' · ativa', ' · active') : ''), async () => {
            if (conta.configurada) { await api(caminho + '/selecionar', 'POST', { conta: conta.id }); await status(); }
            else await iniciar(conta.id);
          });
          if (conta.configurada) botao(L('Desconectar ', 'Disconnect ') + conta.label, async () => {
            const r = await api(caminho + '/sair', 'POST', { conta: conta.id });
            await status();
            if (!r.revogacao_confirmada) texto.textContent = L('Desconectado aqui. Confirme a remoção em Configurações do ChatGPT.', 'Disconnected locally. Confirm removal in ChatGPT Settings.');
          });
        }
      } else if (s.instalado) {
        botao(L('Entrar pelo CLI oficial', 'Sign in with official CLI'), () => iniciar());
        botao(L('Verificar conexão', 'Check connection'), status);
        const comando = document.createElement('code');
        comando.textContent = raiz.dataset.loginTipo === 'claude_cli' ? 'claude auth login' : 'codex login';
        botoes.append(comando);
      } else if (s.instalacao_url) {
        const link = document.createElement('a');
        link.href = s.instalacao_url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        link.textContent = L('Como instalar', 'Installation guide'); botoes.append(link);
        botao(L('Já instalei, verificar', 'Installed, check again'), status);
      }
    } catch (e) { texto.textContent = e.message; }
    finally { lendo = false; }
  }
  void status();
}
