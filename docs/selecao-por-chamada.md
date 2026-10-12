# Seleção por chamada e limites de produto

O RobinBandit tem duas políticas de seleção no núcleo:

- `hybrid` (`reinforced` / Reforçado): tenta uma preferência e mantém a cadeia como fallback.
- `strict`: usa somente o alvo escolhido e falha sem fallback.

O Sentury chama `strict` de Dedicado. Nesse produto, Dedicado significa deixar uma tarefa inteira presa a um único provedor e uma única LLM. O fluxo do Sentury já traduz essa escolha antes de chamar o RobinBandit.

## Decisão para integrações universais

Reforçado é útil fora do Sentury porque expressa uma preferência sem perder a resiliência da cadeia. Ele aceita uma fila ordenada de contas, sem exigir que sejam pagas: assinaturas, créditos, contas gratuitas e sessões autenticadas por CLI podem conviver na mesma fila. Quando todas falham, o Router continua pela cadeia normal.

Integrações Python podem usar `RouteSelection.hybrid()`. Clientes Chat Completions, Responses ou Anthropic podem pedir a fila configurada no painel com o cabeçalho `X-RobinBandit-Mode: reinforced`.

Dedicado não será promovido no painel universal nem na landing. Um cliente genérico que precisa falar diretamente com uma única LLM normalmente pode usar o endpoint daquele provedor; colocar o RobinBandit no meio e desligar seu fallback acrescenta pouca utilidade. O `strict` continua na API de baixo nível por compatibilidade e para integrações que tenham uma razão própria para usá-lo.

## Consequências na interface

- O painel do RobinBandit mostra somente Reforçado, com várias contas reordenáveis.
- Dedicado é configurado e mostrado pela interface do Sentury. O painel do
  RobinBandit não duplica esse controle.
- Os quatro modos globais de fila continuam separados dessa seleção por chamada: Adaptativo, Prioridade por tier, Lista fixa e Rodízio.
- A documentação deve chamar Dedicado de recurso do Sentury, não de capacidade automática de qualquer cliente OpenAI ou Anthropic.

## Imagem anexada com uma conta escolhida

O grupo do Reforçado/Dedicado declara o que as contas dele fazem (`vision`, …), herdado da linha do provedor de cada conta no YAML. Sem isso o Router não achava o grupo no catálogo e o tirava de todo turno com imagem.

| Conta escolhida | Reforçado | Dedicado |
| --- | --- | --- |
| Enxerga | Recebe a imagem. | Recebe a imagem. |
| Não enxerga | Sai do turno; o Router responde com quem enxerga (a preferência continua sendo fallback). | Um provedor do Router que enxerga descreve a imagem; a conta recebe o texto com a descrição e a resposta continua sendo dela. |
| Ninguém enxerga | O Router diz que ninguém lê imagem. | Erro dizendo que a conta não lê imagem e ninguém no Router lê para descrever. |

Num grupo com várias contas, só as que enxergam recebem a imagem. A descrição fica guardada pela imagem e pelo texto (32 entradas): as várias chamadas de um turno não descrevem a mesma imagem de novo. O print do computer use segue a mesma regra: no Dedicado sem visão, o Router descreve o print direto, sem passar pela conta.

## Rotas nomeadas para trabalho auxiliar

Uma rota tem sua própria fila de provedores e seus próprios modelos. Ela pode
ser usada para resumir, compactar histórico ou criar um título sem usar o
modelo escolhido para o turno principal. A seleção Dedicado do Sentury não
é herdada por essa cadeia.

```yaml
routes:
  auxiliar:
    chain_order: [groq, gemini]
    models:
      groq: [openai/gpt-oss-20b]
      gemini: [gemini-2.5-flash-lite]
```

```python
from robinbandit import RobinConfig, build_route

config = RobinConfig.from_yaml("robinbandit.yaml")
auxiliar = build_route(config, "auxiliar")
resumo = await auxiliar.complete([
    {"role": "user", "content": "Resuma o texto fornecido."}
], reasoning_effort="low")
```

`settings` é opcional. As credenciais continuam no cofre ou no ambiente;
`models` define apenas os identificadores. Sem provedor disponível na rota,
a montagem falha claramente, sem cair escondido no modelo principal.
O chamador decide quais tarefas envia para ela. Declarar a rota não altera
automaticamente o modelo das tarefas existentes.
