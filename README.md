# Engenharia de Segurança para Sistemas de IA

Material dos alunos. Autor: **Paulo Cesar Braga**.

Esta entrega acrescenta os laboratórios da **Parte I, capítulos 1 a 4**, à preparação L00, ao piloto L09 de RAG adversarial e aos ensaios M1 de inferência e protocolos. O projeto integral tem 36 capítulos; a publicação destes materiais não significa que o restante esteja concluído.

## Começar pela Parte I

Leia o [guia da Parte I](PARTE_I.md). L01–L04 usam apenas a biblioteca padrão do Python 3.12, dados sintéticos e, no L04, HTTP em loopback. Não precisam de modelos, SDKs ou APIs pagas.

| Laboratório | Objetivo | Evidência local |
| --- | --- | --- |
| L01 | Inventário e requisitos refutáveis | 9 ativos, 6 requisitos, 18 observações |
| L02 | Caminhos e mediação obrigatória | 3 grafos; desvios antes e depois da mudança |
| L03 | Referências e controles sem dupla contagem | 8 associações, 4 mecanismos |
| L04 | Conferência de efeitos no destino | 10 casos HTTP; narrativa falsa detectada |

Os casos L04 produziram três efeitos autorizados, três efeitos proibidos na variante vulnerável, três bloqueios e um erro por recurso inexistente. Os resultados esperados incluem falhas deliberadas. O vínculo final registra C01–C03 com evidência local e C04 ainda planejado. Isso não é uma porcentagem de segurança.

Há 46 testes novos da Parte I. Os 49 testes do piloto e os 15 testes M1 são preservados. As capturas finais novas estão em `output/parte1_v02`. A revisão inicial de desenvolvimento não integra o pacote público.

## Materiais anteriores preservados

O [guia L00/L09/M1](COMECE_AQUI.md) mantém os comandos e limites das extensões. As capturas históricas incluem 40 gerações reais com duas quantizações de Qwen2.5-0.5B-Instruct, 160 trajetórias com inferência e 29 verificações do perfil local de MCP/A2A. Essas execuções não são novos resultados da Parte I. As campanhas Q4/Q8 também registram 22/24 erros por recursos inexistentes, separados dos bloqueios.

## Alcance e organização

Manuscritos, PDFs editoriais, EPUBs, fontes, capas, registros KDP, pesos e executáveis não integram este repositório. Aqui ficam código, testes, materiais sintéticos, locks, guias e capturas selecionadas. O manifesto de pacote identifica os arquivos desta entrega; o Git preserva as versões anteriores dos guias e manifestos.

O L01 avalia observações preparadas. O L02 verifica o grafo declarado. O L03 valida rastreabilidade. O L04 mede comportamento de aplicação com ações preparadas, sem inferência. Processos separados sob o mesmo usuário não demonstram isolamento contra código hostil. A reprodução é local e autoral, sem certificação, teste cego independente ou garantia de produção.

Use pastas novas e preserve os manifestos originais. Alteração de código, configuração, dependência ou modelo exige evidência própria; não recalcule hashes antigos para esconder divergências.
