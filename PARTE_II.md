# Parte II: roteiro executável e critérios de leitura

Autor: Paulo Cesar Braga. Entrega 1.0, 22/10/2026. Execute na raiz do repositório. Dados e marcadores são sintéticos; as variantes vulneráveis pertencem à bancada local, não a um serviço público.

## Preparar Python

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r materiais/parte2/requirements.lock.txt
.venv/Scripts/python -m unittest discover -s testes_parte2 -v
```

Perfil executado: Windows/Python 3.12.0, PyJWT 2.15.1, cryptography 50.0.2, cffi 2.1.1 e pycparser 3.12. Em Linux, os caminhos do Python do venv usam `.venv/bin/python`; esse perfil nativo não foi reproduzido nesta entrega. A suíte inclui verificações da captura Docker fornecida; rodar a suíte não reproduz automaticamente o runtime Linux.

## Executar L05, L06 e L07

```powershell
.venv/Scripts/python -m laboratorios.parte2 run L05 --out output/minha_execucao/l05
.venv/Scripts/python -m laboratorios.parte2 run L06 --out output/minha_execucao/l06
.venv/Scripts/python -m laboratorios.parte2 run L07 --out output/minha_execucao/l07
```

Cada diretório de saída deve ser novo. L05/L06 iniciam servidor HTTP em porta efêmera de loopback, com threads e estado em memória. Fecham o servidor ao terminar. Não usam IdP externo, TLS nem serviços pagos. L07 inicia processo emissor com chave privada efêmera em memória e o encerra ao final. O bootstrap usa pipe separado da distribuição, mas não resiste a comprometimento do usuário do host.

| Captura | Resultado esperado |
|---|---|
| L05 | 16 respostas, 16 eventos, 5 leituras; 5 códigos 200, 10 códigos 401 e 1 código 403 |
| L06 | 66 respostas, 66 eventos, 42 leituras; 42 códigos 200, 21 códigos 403, 2 códigos 404 e 1 código 503 |
| L07 | 10 tentativas; 2 carregamentos; 8 recusas antes de carregar |

L05 contém uma leitura indevida no perfil sem audiência. L06 inclui 27 leituras do perfil com papel amplo e cinco do cache antecipado. Não chame todas as respostas 200 de tarefas legítimas. O erro 503 é indisponibilidade da política, não decisão de autorização. O canário de telemetria é público e não é uma credencial operacional.

O L07 recebe uma configuração JSON, não um modelo treinado. O piso de versão é dois e não é atualizado duravelmente ao aceitar três. O comando `verify` reavalia a aprovação no instante da captura; não renova uma autorização expirada.

## Executar L08 no Docker Linux

Inicie o Docker Desktop com engine Linux. `docker version` precisa mostrar um servidor disponível. O Dockerfile fixa uma imagem Python por digest. Se ela ainda não existir, obtenha a base:

```powershell
$base = 'python@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2'
docker pull $base
.venv/Scripts/python -m laboratorios.parte2 run L08 --out output/minha_execucao/l08
```

O pull exige rede e espaço; seu custo não está incluído na captura. A execução canônica reutilizou a base local. Perfil efetivo: Docker Engine 29.8.2, Linux 6.6.87.2-microsoft-standard-WSL2 e Python 3.12.13 dentro da imagem. A distribuição Ubuntu registrada no host não foi usada; a integração depende do engine Linux do Docker.

O controlador cria nomes `livro-l08-<identificador>`, uma rede interna, um receptor e contêineres de sondas; não usa montagens de pastas do host, modo privilegiado nem socket Docker dentro do executor. A variante permissiva usa UID 0, rede interna e temporário de 32 MiB; a restrita usa UID 10001, raiz somente leitura, rede `none` e temporário de 8 MiB. Ambas retiram capacidades e impedem novos privilégios.

Os perfis principais têm 128 MiB e meia CPU; o limite de processos é 64/16. As sondas tentam no máximo 24 filhos e doze MiB de escrita. O ensaio de memória usa 64 MiB e tenta alocar 180 MiB; o watchdog usa espera de dois segundos e encerra o contêiner. O pico de demanda é limitado por contêiner; isso não inclui a memória total do Docker Desktop.

| Observação | Permissivo | Restrito |
|---|---|---|
| Leitura pública / temporário pequeno | Concluem | Concluem |
| Leitura privada | Conclui | EACCES (13) |
| Escrita na raiz | Conclui | EROFS (30) |
| Escrita de doze MiB | Conclui | ENOSPC (28) |
| Socket direto ao receptor | Um recibo | ENETUNREACH (101), nenhum recibo |
| Criação de filhos | 24 | 15, depois EAGAIN (11) |

Além dessas 14 sondas, a referência registra OOMKilled e timeout com encerramento. A duração total foi aproximadamente 44,1 s com build em cache. RSS principal: 17.612/17.668 KiB. O relatório contém picos de cgroup e durações; esses números não dimensionam o computador inteiro. O inventário final não encontrou recursos temporários com os nomes criados; imagem base e camadas compartilhadas permanecem.

Se o ensaio falhar, preserve `results.json` e `build.log` quando existirem. Não converta falha de inicialização, falta de imagem ou destino indisponível em bloqueio defensivo. Use outro diretório para nova tentativa.

## Conferir capturas publicadas

```powershell
.venv/Scripts/python -m laboratorios.parte2 verify L05 --out output/parte2_v01/l05
.venv/Scripts/python -m laboratorios.parte2 verify L06 --out output/parte2_v01/l06
.venv/Scripts/python -m laboratorios.parte2 verify L07 --out output/parte2_v01/l07
.venv/Scripts/python -m laboratorios.parte2 verify L08 --out output/parte2_v01/l08
```

As capturas vinculam código e materiais por hash e rejeitam inventário incompleto. Os verificadores reconstroem decisões e reconciliam fontes no escopo de cada laboratório. Hash local não é assinatura independente da captura. Os testes de mutação recusam recibo contraditório, perda de tarefa legítima, quota não efetiva, erro de arquivo incorreto e limpeza incompleta.

## Atividades e registro próprio

Use cópias para experimentar: canário em campo permitido de log; cache por usuário sem reautorização; v2 reapresentada depois de v3; montagem excessiva somente leitura com marcadores sintéticos. Antes de executar, escreva a hipótese e o resultado que a refutaria. Registre commit, runtime, comandos, tentativas, recusas, erros, consumo e limites. Os casos publicados são conhecidos pelo autor e não constituem holdout adversarial independente.
