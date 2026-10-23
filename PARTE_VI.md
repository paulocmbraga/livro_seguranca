# Parte VI: roteiro de reprodução

Paulo Cesar Braga · versão 1.0 · 23/10/2026. Capítulos 21–24: treinamento e segurança de modelos. Execute na raiz do repositório, em pastas novas. Os dados são sintéticos; os serviços HTTP ficam exclusivamente em loopback e o modelo consultado em L24 pertence à bancada.

## Ambiente e execução

Perfil executado: Windows, Python 3.12.0, NumPy 2.5.4, SciPy 1.18.1 e scikit-learn 1.9.1. O lock fixa também joblib, threadpoolctl e psutil. Não precisa de GPU, Docker, navegador ou API paga para esta parte. Os outros guias conservam os requisitos de seus laboratórios; este lock não instala todo o acervo histórico.

```powershell
python -m venv .venv
$py = '.venv/Scripts/python'
& $py -m pip install -r materiais/parte6/requirements.lock.txt
& $py -m unittest discover -s testes_parte6 -v
& $py -m laboratorios.parte6 run L21 --out output/minha_execucao/l21
& $py -m laboratorios.parte6 run L22 --out output/minha_execucao/l22
& $py -m laboratorios.parte6 run L23 --out output/minha_execucao/l23
& $py -m laboratorios.parte6 run L24 --out output/minha_execucao/l24
& $py -m laboratorios.parte6 verify L21 --out output/minha_execucao/l21
& $py -m laboratorios.parte6 verify L22 --out output/minha_execucao/l22
& $py -m laboratorios.parte6 verify L23 --out output/minha_execucao/l23
& $py -m laboratorios.parte6 verify L24 --out output/minha_execucao/l24
```

`run` treina e produz capturas; `verify` recalcula relações e previsões dos artefatos, sem reajustar o otimizador. Não use `python -O`: a verificação usa asserts. O runner exige diretório inexistente. Preserve `output/parte6_v02` (referência final) e `output/parte6_qualificacao_v01` (repetição). A suíte nova tem 43 testes e executa os quatro laboratórios, além de contraprovas, concorrência e mutações de capturas com hashes recalculados.

## L21: dados, seleção e promoção

300 registros: 160 de treino, 60 de calibração e 80 de teste. Quatro árvores candidatas são comparadas na calibração; a profundidade 2 vence com 50/60, antes de abrir o teste. A árvore selecionada acerta 72/80. A variante contaminada lê os 80 exemplos finais e os acrescenta ao ajuste, com a profundidade já escolhida; acerta 42/80. A queda foi preservada: contaminação invalida a avaliação independente mesmo quando piora a métrica.

Há 11 chamadas HTTP, quatro contraprovas locais e um recibo válido de promoção. A store estrita resolve papel e partição do lado do servidor. O gate recusa origem alterada, ID inventado, teste/calibração no ajuste e repetição de grupo. O controlador de jobs permanece confiável; a bancada não isola o processo do host nem implementa registry externo. Hashes e eventos locais não são atestação de terceiro.

## L22: veneno, gatilho e adaptação

Três sementes, 400 registros de treino e 160 de avaliação por semente. Há um modelo limpo e cinco condições em cada orçamento 4/16/32: alteração aleatória de rótulos, dirigida, dirigida filtrada, adaptada e adaptada filtrada. Total: 48 regressões logísticas reais. Orçamento iguala registros alterados, não células. O ataque altera rótulos; não representa clean-label poisoning.

O filtro exclui o primeiro marcador; o adaptado usa o segundo. Na semente 11 e orçamento 16, o dirigido produz 61/72 saídas-alvo, preservando 156/160 acertos limpos. O filtro remove os 16 alterados e oito limpos. O adaptado filtrado mantém os 16 alterados e produz 67/72 saídas-alvo. O relatório conserva também novas viradas condicionadas e todas as sementes. Não há revisão humana real da quarentena, detecção geral ou avaliação de LLM.

## L23: domínio, ataque adaptado e utilidade

Treino 400, reserva 120, substituto 200; três modelos ajustados e três variantes (original, quantizada e aumentada). Quatro métodos e quatro raios produzem 48 condições e 5.760 entradas finais. Somente os dois primeiros atributos mudam, dentro de [0,1] e de L-infinito; a verdade latente e os demais atributos são conservados. Essa validade sintética não prova plausibilidade física em sensores reais.

Em epsilon 0,15, diferenças finitas não produzem novos erros no quantizado, mas a grade produz 49/112 novos erros entre inicialmente corretos. O modelo aumentado troca 113/120 por 108/120 acertos limpos e melhora de 67/120 para 79/120 sob a grade. O aumento é de um passo, sem certificação ou otimização robusta completa. A transferência usa gradiente do substituto e duas avaliações da vítima para seleção: não é sem consultas. Os custos de busca excluem baseline e pontuação final, ambos documentados.

## L24: aproximação pela interface própria

Uma floresta de 25 árvores é treinada em 600 exemplos. São 12 campanhas, quatro perfis e três orçamentos solicitados 16/64/128. Cada substituto é uma árvore de profundidade máxima 5, ajustada em respostas admitidas. A reserva tem 400 exemplos, separados das consultas. Rótulos e scores usam classificadora e regressora, respectivamente; a comparação não isola apenas a quantidade de informação da resposta.

Com 128 consultas, fidelidade é 352/400 por rótulos e 360/400 por scores; referência majoritária 217/400. Com cota de 32 por organização, os dois perfis chegam a 324/400. Rotação de duas credenciais e tenant falso não ampliam a cota. Há 1.048 chamadas, 736 inferências (576 adversariais e 160 legítimas) e 312 recusas. Alpha recebe 64/96 respostas legítimas; beta, 96/96. Tráfego adversarial precede o legítimo deliberadamente.

A cota é fixa por experimento, não rate limiting distribuído. Não há detector de intenção, novas organizações, TLS, cobrança, consultas ativas, recuperação de pesos ou garantias contra leitura pelo mesmo usuário do host. Os JSONs numéricos publicados permitem auditoria, enquanto o caminho de ajuste dos substitutos usa apenas as respostas HTTP.

## Recursos e limites de evidência

Repetição sequencial no mesmo computador, com imports e encerramento:

| Laboratório | Segundos | Pico amostrado de RSS da árvore, MiB |
|---|---:|---:|
| L21 | 3,51 | 128,1 |
| L22 | 3,61 | 127,5 |
| L23 | 2,86 | 124,4 |
| L24 | 27,32 | 133,1 |

Amostragem a cada 100 ms, soma de processos próprios vivos; pode contar memória compartilhada mais de uma vez e perder picos. Não inclui instalação/download, RAM total ou máquina dedicada. Não é benchmark de produção. Há treinamento e inferência tabular local; não houve geração de LLM ou chamada cobrada.

Para repetir a medição: `python producao/qualificar_parte6.py --out output/minha_execucao/recursos`. Todos os artefatos devem ser novos. As fontes oficiais e suas versões estão em `materiais/parte6/referencias.lock.json`. Verificar as capturas históricas das outras partes não equivale a reexecutar suas inferências. Reprodução independente, revisão do autor e avaliações em domínios reais permanecem pendentes.
