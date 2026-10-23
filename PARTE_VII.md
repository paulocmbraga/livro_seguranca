# Parte VII: roteiro de reprodução

Paulo Cesar Braga · versão 1.0 · 23/10/2026. Capítulos 25–28: privacidade, adaptação e implantação. Execute na raiz do pacote e em diretórios novos. Todos os dados e tokens de cliente são sintéticos. A bancada não consulta modelos ou serviços de terceiros.

## Ambiente isolado

Qualificado em Windows com Python 3.12.0, NumPy 2.2.6, SciPy 1.15.3, scikit-learn 1.5.2, diffprivlib 0.6.6, PyTorch 2.14.1+cpu e Docker Engine 29.8.2. Os locks incluem dependências auxiliares. Não substitua o ambiente das partes anteriores: as versões atuais de scikit-learn/SciPy usadas na Parte VI não foram compatíveis com o diffprivlib neste ensaio.

```powershell
python -m venv .venv/parte7
$py = '.venv/parte7/Scripts/python'
& $py -m pip install -r materiais/parte7/requirements.lock.txt
& $py -m pip install --no-deps -r materiais/parte7/torch-cpu.lock.txt
& $py -m pip check
& $py -m unittest discover -s testes_parte7 -v
docker version
$base = & $py -c "from laboratorios.parte7.deployment import BASE; print(BASE)"
docker image inspect $base
# Se a base ainda não existir, obtenha a referência fixada:
# docker pull $base
& $py producao/qualificar_parte7.py --out output/minha_execucao/parte7
```

PyTorch CPU é instalado por índice oficial separado e sem resolução adicional: os demais pacotes já estão fixados no primeiro lock. O diretório `.venv/parte7` fica sob o caminho de ambiente ignorado pelo Git. Em Linux, ajuste o caminho do executável para `.venv/parte7/bin/python`; essa plataforma não recebeu reprodução independente nesta entrega. Instalação e downloads não entram nas medidas de tempo dos laboratórios.

O runner executa L25–L28 sequencialmente, cria logs e `resources.json`; o limite por laboratório é 900 segundos. As execuções qualificadas ficaram muito abaixo desse teto. Para executar ou verificar individualmente:

```powershell
& $py -m laboratorios.parte7 run L25 --out output/minha_execucao/l25
& $py -m laboratorios.parte7 run L26 --out output/minha_execucao/l26
& $py -m laboratorios.parte7 run L27 --out output/minha_execucao/l27
& $py -m laboratorios.parte7 run L28 --out output/minha_execucao/l28
& $py -m laboratorios.parte7 verify L25 --out output/parte7_v01/l25
& $py -m laboratorios.parte7 verify L26 --out output/parte7_v01/l26
& $py -m laboratorios.parte7 verify L27 --out output/parte7_v01/l27
& $py -m laboratorios.parte7 verify L28 --out output/parte7_v01/l28
```

Não use `python -O`: os verificadores usam asserts. `run` exige pasta inexistente. `verify` recalcula relações e inferências dos artefatos; não refaz treinamento ou deployment. Os modelos pequenos são próprios e exportados em JSON. Certificados e chaves de L27 são efêmeros; só o fingerprint público entra na captura. A limpeza remove apenas containers, redes e tags criados pela execução, sem prune.

## L25: pertencimento e orçamento

560 registros sintéticos, 80 atributos limitados a [-1,1], 160 no treino. Calibração do ataque: 80 membros + 80 não membros; avaliação: outros 80 + 80; utilidade: 240 separados. O atacante conhece rótulo verdadeiro e probabilidade e escolhe limiar apenas na calibração. Publicam-se escores, coeficientes, matriz de confusão, AUC, vantagem e projeção de precisão com prevalência de 1%.

Há um ajuste não privado e três regressões logísticas do diffprivlib com epsilon 0,5, 2 e 8; o BudgetAccountant compõe 10,5, delta 0, slack 0, e bloqueia ajuste adicional de 0,1. A norma máxima pública é raiz de 80. O caminho `random_state=None` foi conferido até SystemRandom no mecanismo. Não fixe uma semente pública para o ruído. Repetições produzem valores diferentes, e cada captura deve ser reconciliada por seus próprios coeficientes.

Na referência, o modelo não privado teve 78 TP e 47 FP entre 80 membros/80 não membros; utilidade 161/240. Os modelos privados tiveram respectivamente TP/FP de 50/53, 39/33 e 0/0; utilidade 115, 134 e 115 de 240. Vantagem negativa é preservada, não invertida depois do teste. Resultado empírico de um ataque não comprova nem refuta sozinho a garantia formal. Como corpus, baseline e escores são sintéticos públicos, o pacote inteiro **não** é uma publicação DP de dados confidenciais.

## L26: adaptação realmente treinada

Modelo condicional de próximo token com embedding 16, GRU 32 e 12 saídas. Base e dois ajustes totais usam 5.804 parâmetros treináveis; adaptador na cabeça usa 176, posto 4. Não é LoRA de Transformer nem LLM pré-treinado. Passos: 400 da base, 400 contaminado, 400 curado e 800 adaptador. Dados/IDs finais são separados para tarefa; os oito prefixos de canário são consultas conhecidas de treino, identificadas separadamente.

| Modelo | Domínio / 8 | Recusas / 24 | Geral / 16 | Canários / 8 |
|---|---|---|---|---|
| Base | 0 | 24 | 16 | 0 |
| Contaminado | 8 | 0 | 0 | 8 |
| Curado | 8 | 24 | 16 | 0 |
| Adaptador | 7 | 24 | 11 | 0 |

Os pesos, checkpoints, curvas de perda, dados e previsões estão nas capturas. A variante contaminada foi deliberadamente instruída a violar controles: não se alega degradação involuntária. O adaptador é ligado ao hash da base e seus demais tensores permanecem iguais. A reversão restaura previsões da base; não desfaz uma exposição já ocorrida. Avaliação autoral pequena e sintética, sem teste de linguagem natural ou ataques desconhecidos.

## L27: rede, TLS e cache

Dois perfis Docker, seis containers no total, quatro redes internas. Backend sem porta publicada; gateway publicado apenas em 127.0.0.1. No perfil estrito, o cliente não alcança diretamente o IP do backend; o gateway o alcança, recebe 401 sem credencial de serviço e 200 com ela. TLS exige confiança explícita e nome correto; ambas as contraprovas de certificado falham. Ligação interna gateway–backend usa HTTP e token sintético, sem mTLS.

O perfil fraco compartilha cache entre alpha e beta. O estrito vincula tenant, recurso, modelo e versão, conferindo recibos no backend. A sexta predição de alpha recebe 429, incluindo cache hits na cota; beta mantém orçamento. Batching é recusado, não implementado. Rota administrativa é fechada no perfil estrito. Servidor sequencial, cota em memória, sem teste de carga/concorrência ou garantias contra administrador Docker.

## L28: gate e reversão

Três bundles reproduzidos byte a byte e três imagens reais. Testes sem rede rodam dentro da imagem final. v1/v2 passam em cinco verificações; regression passa no funcional mas falha em isolamento/administração e é barrado. Evidência vinculada a outro bundle/imagem também é barrada. Os testes de unidade verificam relatório vazio, campos ausentes, strings verdadeiras e exceções expiradas ou fora de escopo.

Quatro smokes HTTP: v1 passa, v2 passa, v2 com configuração alterada pelo controlador falha, v1 restaurado passa. O arquivo `active_release.json` é o estado final do experimento; nenhum serviço permanece ativo após a limpeza. Não há CI hospedada, registry externo, assinatura de terceiros ou rollback de banco/efeitos. A imagem usa modelo linear fixo; o treinamento real pertence aos L25/L26.

## Recursos, repetição e evidência

Na referência: L25 4,08 s/127 MiB; L26 10,74 s/279 MiB; L27 91,33 s/96 MiB; L28 91,87 s/101 MiB. RSS é soma amostrada dos processos clientes próprios, pode contar páginas compartilhadas e perder picos, **não inclui a VM Docker/containers**. Esses números não são requisitos mínimos nem benchmark de produção. A repetição levou 3,82/11,22/91,67/77,90 segundos, respectivamente.

43 testes novos e 327 anteriores foram executados no pacote exportado, usando os respectivos ambientes; 62 trabalhos incluem testes e reconciliação de capturas. As duas execuções completas da Parte VII ocorreram no mesmo computador. A reprodução por outra equipe continua pendente. Fontes oficiais e versões estão em `materiais/parte7/referencias.lock.json`; manifestos de cada captura vinculam código, materiais e artefatos.
