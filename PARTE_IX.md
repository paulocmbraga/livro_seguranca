# Parte IX: garantia de segurança e casos completos

Paulo Cesar Braga · 23/10/2026 · versão 1.0. Capítulos 33–36. Dados sintéticos, execuções locais e destinos lógicos; nenhuma API paga.

## Ambiente próprio

Execute na raiz do repositório. Preserve os ambientes das partes anteriores: o conjunto de bibliotecas ML da Parte IX utiliza NumPy 2.2.6, SciPy 1.15.3, scikit-learn 1.5.2 e diffprivlib 0.6.6, junto aos SDKs MCP 2.3.0 e A2A 1.2.3. Python de referência: 3.12.0, Windows. O perfil Linux do host não foi reproduzido; os workers/serving Docker usam Linux.

```powershell
python -m venv .venv/parte9
& .venv/parte9/Scripts/python.exe -m pip install -r materiais/parte9/requirements.lock.txt
& .venv/parte9/Scripts/python.exe -m pip check
& .venv/parte9/Scripts/python.exe -m unittest discover -s testes_parte9 -v
```

São 55 testes novos. Os testes de Ledger usam um worker substituto identificado; a execução completa L36 é que cria contêineres reais. O pacote cumulativo é validado separadamente, com os ambientes apropriados às versões históricas.

L34 e L36 exigem Docker Linux ativo e a base `python@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2`. O L36 recusa pull automático; prepare a base antes de executar em outra máquina. O L34 constrói duas imagens próprias com rede de build desativada. Nenhuma porta é publicada fora do loopback. O serving L34 usa bridge; o worker L36 usa rede none. Não atribua ao primeiro o bloqueio de saída demonstrado no segundo.

L35 requer os dois GGUF e llama.cpp b11669 de `materiais/m1/artefatos.lock.json`, conforme [COMECE_AQUI.md](COMECE_AQUI.md) e [PARTE_III.md](PARTE_III.md). Não há download automático de modelos. O cache local de referência é `../tmp/seguranca_m1`; ajuste somente seu caminho e conserve os hashes. Q4_K_M e Q8_0 são quantizações dos mesmos pesos Qwen2.5-0.5B-Instruct.

## Executar e preservar resultados

```powershell
& .venv/parte9/Scripts/python.exe -m laboratorios.parte9 run L33 --out output/minha_execucao/l33
& .venv/parte9/Scripts/python.exe -m laboratorios.parte9 run L34 --out output/minha_execucao/l34
& .venv/parte9/Scripts/python.exe -m laboratorios.parte9 run L35 --cache ../tmp/seguranca_m1 --out output/minha_execucao/l35
& .venv/parte9/Scripts/python.exe -m laboratorios.parte9 run L36 --out output/minha_execucao/l36
```

Cada run recusa diretório existente. Não apague diagnóstico para obter uma captura aparentemente limpa. Não use `python -O`: os verificadores usam assertions. O roteiro medido de toda a parte é:

```powershell
& .venv/parte9/Scripts/python.exe producao/qualificar_parte9.py --out output/minha_execucao/campanha --cache ../tmp/seguranca_m1
```

## Evidências e limites por laboratório

| Laboratório | Execução nova | Limites principais |
|---|---|---|
| L33 | Seis decisões de dossiê, fixture e referências históricas | Elegibilidade didática; não aprovação humana ou certificação |
| L34 | Três ajustes, cem passos de adaptação, duas imagens, 32 tentativas HTTP | Reserva conhecida pelo autor; DP com seed pública; quota por processo |
| L35 | FTS5, memória, 28 gerações reais, quatro sondas preparadas, revogação | Dois perfis dos mesmos pesos; citação vinculada não é factualidade |
| L36 | Oito cenários, 22 chamadas SDK e uma alternativa, 23 workers Docker | Especialista preparado; host/emissor/recurso confiáveis; sem TLS/federação |

L34 preserva o controle contaminado: 41 novas mudanças entre 53 negativos elegíveis, apesar de 110/120 acertos limpos. O modelo DP tem 112/120 acertos e 14 falhas novas em 112 elegíveis sob perturbação branca de 0,08. Sete respostas de extração sustentam substituto com 85% de fidelidade. A decisão de bancada aceita strict e recusa weak pela identidade no cache; não promete robustez absoluta.

L35 registra contexto enviado, resposta bruta, proposta, apresentação, fallback, exposição e recibo. Em cada quantização, weak tem duas linhas estrangeiras e quatro recibos indevidos com a sonda; strict tem zero. Os três controles legítimos mantêm efeito. No estrito, uma citação gerada vinculada mais quatro fallbacks resultam em cinco respostas com fonte; duas ficam sem fonte autorizada. Não atribua os fallbacks ao LLM. A recuperação remove memória/candidatos e limpa cache, conservando evidência sintética.

L36 conserva oito recibos no weak e quatro no strict. Replay não duplica escrita; revogação e cancelamento são revalidados no recurso após o worker. A falha de resposta perdida é um estado unknown retornado pela aplicação após commit, não timeout real de rede. Tokens têm validade de 120 s; são renovados entre cenários e antes do cliente alternativo. Os horários públicos de emissão/expiração são capturados, sem bearer ou chave privada. Aprovações são fixtures, não manifestações de uma pessoa real.

## Conferir a referência e a repetição

Referência final: `output/parte9_v02`. Repetição: `output/parte9_qualificacao_v01`. Ambas executadas integralmente no mesmo host, sem reprodução independente. Diagnósticos anteriores permanecem no acervo editorial privado e não foram reclassificados como execução final.

```powershell
foreach ($capture in 'parte9_v02','parte9_qualificacao_v01') {
    foreach ($lab in 'L33','L34','L35','L36') {
        $leaf = $lab.ToLower()
        & .venv/parte9/Scripts/python.exe -m laboratorios.parte9 verify $lab --out "output/$capture/$leaf"
    }
}
```

Verificar reconcilia fontes, inventário e fatos registrados. Não reexecuta treino, modelos, Docker ou protocolos. IDs de tarefas, portas, assinaturas, imagens e tempos podem variar. Compare métricas e consequências com suas condições; não normalize falhas para forçar igualdade.

## Recursos medidos e revisão independente

| Referência final | Tempo total do subprocesso | Pico RSS amostrado da árvore própria |
|---|---|---|
| L33 | 1,32 s | 66,57 MiB |
| L34 | 41,61 s | 201,70 MiB |
| L35 | 77,03 s | 725,14 MiB |
| L36 | 115,85 s | 149,48 MiB |

Amostragem de 100 ms; inclui importação e encerramento. Pode perder picos e somar páginas compartilhadas. Exclui instalação/download, memória total do host e memória do daemon/contêineres Docker. Portanto, 149 MiB não é requisito de RAM do L36. O host é compartilhado; estes números não são SLA ou benchmark comparativo. Os recursos dos servidores llama.cpp também estão nas capturas individuais.

A reprodução independente deve partir de um checkout identificado, instalar o lock, conferir cache/base e executar os quatro laboratórios em diretório novo. Registre divergências, erros e custos, inclusive quando a campanha não termina. Questione candidato, escopo e consequência de cada alegação. O capítulo 33 fornece perguntas e um pedido de revisão ainda não iniciado. Não há revisor atribuído, aprovação externa ou liberação de produção.

O material público contém código, testes, dados sintéticos, pequenos modelos próprios em JSON, guias e capturas. Manuscritos, PDFs, fontes, capas, chaves privadas, pesos de LLM e arquivos comerciais ficam fora. Histórico anterior preservado. A conclusão dos 36 capítulos não encerra apêndices, revisão independente, composição integral ou publicação comercial.
