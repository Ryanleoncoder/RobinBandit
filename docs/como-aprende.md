# Como o RobinBandit aprende

Resposta curta: **não é rede neural. É aprendizado por reforço bayesiano.**

Não há `torch`, `sklearn` nem `numpy` no roteador. Isso é escolha, não
limitação — o porquê está no fim.

---

## 1. Thompson Sampling com posterior Beta

Cada par **(contexto, provedor)** tem uma célula `Beta(α, β)`. `α` acumula o
que deu certo, `β` o que deu errado.

Na hora de escolher, ele **sorteia** da distribuição em vez de usar a média:

```python
q = self._rng.betavariate(quality.alpha, quality.beta)   # router.py
```

O sorteio é o mecanismo inteiro. Quem tem poucas amostras tem distribuição
larga: às vezes sorteia alto e ganha uma chance de provar o que vale. Quem já
se provou tem distribuição estreita e vence quase sempre.

Isso resolve exploração contra aproveitamento sem nenhum parâmetro arbitrário
— não existe um `epsilon` para alguém calibrar errado. A incerteza vira
exploração sozinha, e some sozinha quando deixa de existir.

## 2. Decaimento por recência, com teto

```python
cell.alpha = max(0.2, cell.alpha * _DECAY) + d_alpha
if cell.alpha + cell.beta > _SAMPLE_CAP:   # normaliza mantendo a média
```

Duas guardas, cada uma contra um jeito de travar:

- **Decaimento**: o passado pesa menos que o presente. Um provedor que piorou
  hoje não fica protegido pelo que fez no mês passado.
- **Teto de amostras**: sem ele, depois de milhares de observações a
  distribuição fica tão estreita que nada mais muda de opinião — o roteador
  viraria uma regra fixa que só *parece* estar aprendendo.

E um piso (`0.2`) para a célula nunca colapsar em certeza absoluta.

## 3. Peak EWMA para latência

Média móvel exponencial **assimétrica**: um pico entra no score na hora, a
recuperação decai devagar. Vem do Finagle/Envoy e não é aprendizado — é
estatística de série temporal. Degradar custa caro imediatamente; voltar ao
normal precisa se provar em várias amostras.

## 4. Contextual

O aprendizado é indexado por contexto (tipo de tarefa, tier). "Quem é melhor"
é resposta **por situação**, não um ranking global — o provedor bom para
planejar pode ser ruim para responder.

## 5. O que NÃO é aprendido

Fica fora de propósito, como regra declarada em YAML:

- classificação de erro e tempo de cooldown (`routing.erros`)
- penalidade por classe de custo (`cost_penalties`)
- tier, prioridade e qualidade inicial (priors por provedor)
- ordem da cadeia (`chain_order`)

Priors são um palpite inicial, iguais para todo mundo. O aprendizado corrige
o palpite com o que acontece nesta máquina.

---

## Por que não rede neural

1. **Volume de dados.** Uma rede precisa de milhares de exemplos rotulados.
   Um roteador vê dezenas de decisões por dia. Thompson Sampling converge com
   pouquíssimas amostras e tem garantia teórica de arrependimento.

2. **Auditabilidade.** Você abre `~/.robinbandit/ranking.json` e lê `alpha` e
   `beta` por provedor. Uma rede seria uma caixa-preta decidindo onde o
   dinheiro vai — e quando escolhesse errado, não haveria o que inspecionar.

3. **Custo.** O roteador roda antes de **toda** chamada. Inferência de rede
   nesse caminho acrescentaria latência ao próprio mecanismo que existe para
   reduzir latência.

4. **Partida a frio.** Uma rede sem treino não sabe nada e precisa de um
   período ruim para aprender. O posterior Beta começa em ignorância
   declarada e explora de forma útil desde a primeira chamada.
