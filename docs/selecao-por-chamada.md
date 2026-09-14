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
