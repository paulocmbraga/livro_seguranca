# Revisão integral 1.1 — correções e reprodução

Engenharia de Segurança para Sistemas de IA · Paulo Cesar Braga · 23/10/2026.
Este complemento acompanha a prova editorial v02. O PDF e as soluções
editoriais permanecem no acervo privado; este repositório distribui os
laboratórios, testes, materiais sintéticos, capturas e guias dos alunos.

## L15: fechamento explícito de conexões SQLite

A execução histórica da suíte da Parte IV apresentou uma falha intermitente
na remoção de um banco SQLite no Windows. A repetição passou, sem corrigir
a causa. Os arquivos históricos continuam disponíveis e não foram reescritos.

A variante `apoio_revisao.privacidade` fecha todas as conexões com
`contextlib.closing`, preservando a transação interna com `with db`.
O contexto de uma conexão SQLite confirma ou reverte a transação, mas **não
fecha a conexão**. A distinção está documentada na
[referência oficial do Python 3.12](https://docs.python.org/3.12/library/sqlite3.html#how-to-use-the-connection-context-manager).

Na raiz deste repositório, com o Python 3.12 já preparado conforme
[COMECE_AQUI.md](COMECE_AQUI.md):

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py -m unittest discover -s testes_revisao -v
& $py -m apoio_revisao verify --out output/revisao_v02/l15
& $py -m apoio_revisao run --out output/minha_revisao/l15
& $py -m apoio_revisao verify --out output/minha_revisao/l15
```

Escolha uma pasta ainda inexistente para `run`: a variante recusa sobrescrever
capturas. O selo próprio `L15-conexoes-1.1` verifica o código desta variante,
os bytes dos artefatos e as propriedades da campanha. Capturas antigas devem
continuar sendo verificadas pelo verificador antigo.

Oito testes verificam confirmação e reversão de transação, fechamento também
em exceção, campanha completa sem coleta de lixo e com referências fortes às
conexões, proteção contra sobrescrita e adulteração de resultados. Na campanha
de referência, as oito chamadas preservam o total 55; após a limpeza, cache e
cofre estão vazios, enquanto os oito registros de auditoria permanecem.
Esses resultados não provam exclusão nas cópias internas de um provedor real.

## Ajustes na leitura do livro

- Capítulo 2 e abertura da Parte II: HTTP 404 não prova inexistência; o servidor
  pode estar ocultando a existência de um recurso proibido. Ver
  [RFC 9110, seção 15.5.5](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.5).
- Capítulo 9: o exemplo exige documentos recuperados antes de `all(...)`,
  evitando uma aprovação vazia; o roteiro explicita os comandos da campanha
  preparada. O adaptador preparado não representa inferência de um LLM real.
- Capítulo 12: título e descrição distinguem formas de memória de suas
  representações derivadas.
- Capítulo 15: a figura separa auditoria, ferramenta, cache e usuário. O
  controlador constrói as cópias a partir do cadastro e da resposta; a
  projeção ao usuário contém somente o total em todos os perfis.
- Capítulo 16: a figura mostra a confirmação de início antes do encerramento
  do worker e a consulta do recibo antes da reconciliação da reserva.
- Capítulo 34: o orçamento do exemplo é por processo; não há promessa de
  persistência entre reinicializações.
- Capítulo 35: a demonstração de revogação começa por uma recuperação positiva.
- Capítulo 36: o worker devolve o resultado ao controlador no host, que acessa
  o recurso SQLite; não existe conexão direta worker–banco nesse laboratório.
- Apêndice B: L0 é contagem de coordenadas alteradas, não uma norma matemática.
- Solução E.4: preserva-se a evidência anterior e publica-se uma nova versão
  corrigida; não se transforma o relatório antigo na versão corrigida.
- Comandos usam explicitamente o Python do ambiente virtual; os guias M1
  públicos foram distinguidos do caderno editorial privado.

## Escopo da validação

A revisão executou os 85 exemplos Python impressos e os oito testes novos.
Os 516 testes da entrega integral anterior são evidência histórica; esta
revisão não repete a campanha completa de inferência e Docker. A correção de
conexões aplica-se à variante nova; a implementação antiga da Parte IV é
preservada para rastreabilidade e pode reproduzir sua falha de limpeza.

Não há qualificação independente, certificação de segurança ou validação de
produção. Testes de software e os 516 exercícios editoriais são contagens
distintas. A diagramação e a paginação são verificadas no PDF privado.
