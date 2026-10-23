# Reprodução dos laboratórios

Execute a partir da raiz deste repositório. Perfil validado: Windows, Python 3.12.0, CPU de seis núcleos, aproximadamente 15,4 GiB de RAM física. Esse é o ambiente medido, não uma especificação mínima universal.

## 1. Núcleo sem dependências externas

```powershell
python -m unittest discover -s testes -v
python -m laboratorios.l09 run --out output/minha_execucao/l09
python -m laboratorios.l09 verify --out output/minha_execucao/l09
```

O modo padrão é `prepared`: interpreta propostas roteirizadas e testa seus efeitos. Não realiza geração de linguagem. A/B contêm uma vulnerabilidade deliberada; C/D impõem identidade e destino no domínio. Os serviços usam apenas loopback e contratos sintéticos.

## 2. Ambiente M1

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r materiais/m1/requirements.lock.txt
.venv/Scripts/python.exe -m laboratorios.l00 --out output/minha_execucao/ambiente.json
.venv/Scripts/python.exe -m unittest discover -s testes_m1 -v
```

O lock é específico do perfil Windows testado. Em Linux/macOS, prepare um lock próprio e execute as verificações antes de declarar compatibilidade. O diagnóstico não inicia modelos nem serviços. Versões instaladas, funcionamento do transporte e eficácia da política são observações diferentes.

## 3. Inferência local real

O comando de preparação baixa aproximadamente 1,11 GiB das origens oficiais registradas no lock, verifica SHA-256 e extrai o runtime portátil. Os arquivos ficam fora do Git. Não há instalação de serviço permanente nem chamada a API de inferência paga.

```powershell
.venv/Scripts/python.exe -m laboratorios.l00.artifacts --cache ../tmp/seguranca_m1 --download
.venv/Scripts/python.exe -m laboratorios.m1.inference --config q4_k_m --cache ../tmp/seguranca_m1 --out output/minha_execucao/rag_q4
.venv/Scripts/python.exe -m laboratorios.m1.inference --config q8_0 --cache ../tmp/seguranca_m1 --out output/minha_execucao/rag_q8
```

São 20 chamadas por configuração, temperatura zero, seed 17, quatro threads de CPU, contexto de 2.048 tokens e no máximo 128 tokens gerados por chamada. O adaptador limita novas chamadas a 900 segundos e cada requisição a 120 segundos. Os modelos são pequenos e produzem erros semânticos; não são uma recomendação de assistente de produção.

Cada caso gera uma proposta reaproveitada entre quatro variantes. O arquivo `inference_ledger.json` preserva as requisições e respostas reais. `resources.json` registra a RSS amostrada do processo servidor, não a RAM total do experimento. Os bancos SQLite do domínio e do destino registram consequências.

## 4. MCP e A2A

```powershell
.venv/Scripts/python.exe -m laboratorios.m1.protocols --out output/minha_execucao/protocolos
```

O ensaio usa os SDKs oficiais sobre HTTP real. MCP negocia 2026-07-28; A2A usa protocolo 1.0 com HTTP+JSON. A chave de teste, segredos de clientes e tokens são efêmeros. Os relatórios não gravam essas credenciais.

O emissor local demonstra um perfil limitado de client_credentials. Não há TLS, PKCE, login de usuário, federação, rotação, revogação ou antirreplay. As chaves públicas são provisionadas pela bancada. A2A mantém estado em memória, com criação, consulta, artefato e cancelamento de tarefa sintética; não há streaming, push, retomada após queda ou LLM nesse ensaio.

## 5. Reconciliar a evidência

```powershell
.venv/Scripts/python.exe -m laboratorios.m1.verify --out output/minha_execucao/rag_q4
.venv/Scripts/python.exe -m laboratorios.m1.verify --out output/minha_execucao/rag_q8
.venv/Scripts/python.exe -m laboratorios.m1.verify --out output/minha_execucao/protocolos
```

Capturas incluídas: `output/l09_eval_v03`, `output/m1_v01/rag_q4`, `output/m1_v01/rag_q8` e `output/m1_v01/protocolos_v03`. O sufixo de protocolos identifica a captura final após correções de compatibilidade. Para o L09 histórico, use seu próprio comando `laboratorios.l09 verify`.

O verificador compara hashes, cardinalidade e eventos. Um erro de execução não equivale a bloqueio de ataque. Um manifesto não é uma assinatura de autenticidade. Se o código mudar, preserve a versão anterior e produza uma nova captura em vez de recalcular os hashes antigos.

## Problemas frequentes

- **Diretório já existe:** escolha outro destino. A recusa protege capturas anteriores.
- **Download .partial:** preserve o arquivo para diagnóstico e tente em outra pasta. Não o renomeie como se estivesse validado.
- **Modelo não inicia:** consulte o log criado no diretório de cache, confira os hashes e a memória disponível.
- **404 no domínio:** a proposta pode conter um recurso inexistente. Consulte o ledger e mantenha a classificação de erro.
- **401/403 na campanha negativa:** podem ser o resultado esperado; a comparação está em `results.json`.
- **Manifesto diverge:** confira o checkout e o arquivo alterado. Não use a divergência como motivo para substituir a evidência histórica.

As bibliotecas, pesos e runtime preservam suas licenças de origem. O lock registra versões e referências; ele não substitui análise de dependências nem qualificação da plataforma para uso em produção.
