# Engenharia de Segurança para Sistemas de IA

Material dos alunos. Autor: **Paulo Cesar Braga**.

Este repositório acompanha os laboratórios do livro em desenvolvimento. A entrega atual contém a preparação L00, o piloto L09 de RAG adversarial e a qualificação M1 de inferência e protocolos autenticados. O manuscrito, o PDF do livro e as artes não fazem parte deste pacote.

## Começar

Leia [COMECE_AQUI.md](COMECE_AQUI.md). O perfil qualificado é Windows com Python 3.12. O núcleo L09 usa apenas a biblioteca padrão. As extensões precisam do ambiente e dos artefatos indicados nos locks; usam CPU, HTTP loopback e dados sintéticos.

| Material | Local |
| --- | --- |
| Preparação e diagnóstico | `laboratorios/l00` |
| RAG adversarial preparado | `laboratorios/l09` |
| Inferência real e MCP/A2A | `laboratorios/m1` |
| Regressão do piloto | `testes` |
| Contratos adicionais | `testes_m1` |
| Dependências e modelos fixados | `materiais/m1` |
| Capturas do piloto e M1 | `output` |

## Evidência desta versão

- 49 testes do piloto e 15 testes M1 aprovados na preparação da entrega.
- 40 gerações reais: Qwen2.5-0.5B-Instruct em Q4_K_M e Q8_0, duas quantizações da mesma família.
- 160 trajetórias com inferência, além das 160 trajetórias da referência preparada.
- 29 verificações do perfil HTTP de MCP/A2A, incluindo credenciais e autorização por recurso/tarefa.

As campanhas de inferência produziram também 22 e 24 erros de execução por recursos inexistentes. Eles permanecem registrados, separados de recusas de autorização. O JSON guiado não garante uma proposta semanticamente válida.

Os resultados são locais e autorais. Não há avaliação cega independente, certificação de protocolo, garantia de segurança de produção ou demonstração de isolamento contra código hostil. As tarefas A2A são sintéticas e mantidas em memória. Os dados não contêm informações de clientes reais.

## Estado do livro

O projeto editorial tem 36 capítulos em nove partes. A publicação progressiva dos materiais não significa que todos os capítulos estejam escritos ou que todos os laboratórios já tenham sido executados. A próxima etapa editorial é a Parte I, capítulos 1–4.

Use uma pasta nova para cada execução. Preserve as capturas incluídas e não atualize seus manifestos para ocultar diferenças. Mudanças de SDK, runtime ou modelo exigem uma nova prova e uma explicação do que mudou.
