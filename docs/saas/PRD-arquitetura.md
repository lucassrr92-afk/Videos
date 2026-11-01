# ClipForge SaaS: PRD e arquitetura do MVP

> **Atualização (01/11/2026): substituído.** Você decidiu que o app é de **uso pessoal**, sem planos ou cobrança e sem Base44. A versão atual é o app web do `README.md` (FastAPI, com upload de vídeo e senha de acesso). Este documento fica só como referência caso um dia vire SaaS.
>
> Status original: **proposta para aprovação**. Nada deste documento foi implementado ou implantado ainda.
> Ponto de partida: o app local da branch `claude/clipforge` (pipeline Python de download, transcrição, escolha de cortes, render e publicação). Esse pipeline foi testado só com vídeo e transcrição simulados.

---

## 1. Objetivo

Plataforma web em que criadores de conteúdo enviam um vídeo longo (upload ou link) e recebem cortes verticais editados, com legendas, prontos para YouTube Shorts, TikTok e Instagram Reels. Os cortes podem ser revisados, ajustados e publicados de dentro da plataforma.

**Métrica de sucesso do MVP:** porcentagem de projetos em que o usuário exporta ou publica pelo menos 1 corte, e tempo do upload até o primeiro corte pronto.

## 2. Usuários

| Persona | Necessidade | Plano provável |
|---|---|---|
| Criador solo (podcast, live, aula) | Transformar 1 vídeo longo por semana em 5 a 10 cortes sem saber editar | Criador |
| Social media / agência pequena | Atender vários clientes, com contas e marcas separadas | Profissional |
| Curioso / avaliação | Testar a qualidade antes de pagar | Gratuito |

## 3. Escopo

### MVP: o que entra
1. Cadastro e login (e-mail com link mágico e Google), com uma organização pessoal criada no cadastro.
2. Novo projeto por **upload de arquivo** (MP4, MOV, WebM, até 2 h e 4 GB) e por **link do YouTube** (veja a seção 10, risco R1).
3. Processamento assíncrono com progresso real: download/ingestão → transcrição → escolha dos cortes → render.
4. Lista de cortes sugeridos com nota de potencial (apresentada como **estimativa, não garantia**), título-gancho, legenda do post e hashtags.
5. Editor do corte: ajuste de início e fim pela transcrição ou por uma timeline, correção do texto da legenda, estilo da legenda (4 presets), enquadramento (seguir rosto ou fundo desfocado), título-gancho, liga/desliga da remoção de silêncios.
6. Exportação MP4 1080×1920 com download por URL assinada.
7. Conexão de contas e publicação em YouTube, TikTok e Instagram, **manual por corte** (veja R3).
8. Planos e créditos em **minutos de vídeo processado**, com cobrança recorrente via Asaas (Pix, boleto e cartão).
9. Configurações da conta: excluir projeto, excluir conta e exportar dados (LGPD).
10. Marca d'água no plano gratuito.

### V1: depois do MVP
Agendamento de posts, múltiplos membros por organização (convites e papéis), kit de marca (fonte, cores, logo, intro e outro), legendas em outros idiomas e tradução, B-roll e emojis automáticos, ajuste manual da posição do enquadramento por plano, API pública.

### V2
Analytics dos posts (views, retenção) realimentando o score, workspaces de agência com aprovação do cliente, dublagem, templates de layout (duas pessoas em tela dividida, gameplay + rosto), app mobile.

### Fora de escopo
Edição livre com várias trilhas (estilo editor de vídeo completo), hospedagem de vídeos para o público, músicas licenciadas.

## 4. Histórias de usuário e critérios de aceite (MVP)

| # | História | Critérios de aceite |
|---|---|---|
| H1 | Como visitante, quero criar conta com e-mail ou Google | Conta e organização pessoal criadas; plano Gratuito ativo com 60 min de crédito; e-mail verificado antes do primeiro processamento. **Erros:** link expirado, e-mail já usado em outro método. **Telemetria:** `signup_completed`. |
| H2 | Como usuário, quero enviar um vídeo longo | Upload direto para o storage via URL assinada multipart, com barra de progresso e retomada. O servidor valida MIME real (ffprobe), duração, tamanho e codec. Antes de iniciar, mostra quantos minutos serão consumidos. **Erros:** formato inválido, arquivo corrompido, acima do limite do plano, sem créditos (com CTA de upgrade). |
| H3 | Como usuário, quero colar um link do YouTube | Valida a URL, consulta duração e título antes de cobrar e exige marcar "tenho direitos sobre este vídeo". **Erros:** vídeo privado, com restrição de idade, ao vivo, bloqueio do YouTube (mensagem sugerindo upload do arquivo). |
| H4 | Como usuário, quero acompanhar o processamento | Etapa e porcentagem reais, atualizadas a cada 3 s ou menos. Posso sair da página e voltar. E-mail ao concluir. Em falha: mensagem clara, créditos estornados automaticamente e botão "tentar de novo". |
| H5 | Como usuário, quero ver os cortes sugeridos | Grade com preview, duração, nota de potencial com tooltip "estimativa", título-gancho e motivo da escolha. Posso descartar, duplicar ou abrir no editor. |
| H6 | Como usuário, quero ajustar um corte | Preview no navegador reflete enquadramento, legenda e trecho (aproximação). "Salvar e renderizar" gera o MP4 final sem consumir créditos extras (o crédito é cobrado na análise do vídeo). Edições ficam salvas como rascunho. |
| H7 | Como usuário, quero publicar nas redes | Conecto cada rede via OAuth. Na publicação, preencho título, legenda e privacidade, cumprindo as regras de UX do TikTok Direct Post (veja R3). Vejo o status (enviando, publicado com link, falhou com motivo) e posso tentar de novo. |
| H8 | Como usuário, quero assinar um plano | Checkout Asaas (Pix, boleto, cartão). O plano só é ativado pelo webhook confirmado. Vejo o histórico de faturas e posso cancelar (acesso até o fim do período). |
| H9 | Como usuário, quero excluir meus dados | Excluir projeto apaga os arquivos do storage em até 24 h. Excluir conta apaga tudo e revoga os tokens das redes. Registro em log de auditoria. |

**Regra para toda funcionalidade:** permissões verificadas no servidor por organização, estados de erro definidos, evento de telemetria e teste automatizado.

## 5. Telas e fluxos

```
/login ─► /app (dashboard)
            ├─ [Novo projeto] ─► /app/new  (upload | link + confirmação de direitos + custo em minutos)
            │                       └─► /app/p/:id  (processando: etapas + progresso)
            │                               └─► /app/p/:id  (grade de cortes)
            │                                       └─► /app/p/:id/c/:clipId  (editor)
            │                                               └─► modal Publicar / Baixar
            ├─ /app/accounts   (YouTube, TikTok, Instagram: conectar/desconectar)
            ├─ /app/billing    (plano, saldo de minutos, faturas, upgrade)
            └─ /app/settings   (perfil, idioma padrão, estilo padrão de legenda, excluir conta)
```

**Dashboard:** saldo de minutos (barra), projetos recentes com status, botão principal "Novo projeto".

**Editor** (desktop: 3 colunas; mobile: abas):
- Esquerda: lista de cortes do projeto.
- Centro: preview 9:16. Usa um proxy 720p do original, com o recorte aplicado via CSS e as legendas desenhadas em canvas a partir da transcrição. Isso dá um preview instantâneo sem render.
- Direita: abas Trecho (transcrição clicável com seleção de início e fim, mais timeline com alças), Legenda (preset, cor, tamanho, posição, texto por palavra), Enquadramento (seguir rosto / desfocado), Gancho (texto e duração), Post (título, legenda, hashtags).
- Rodapé: "Renderizar", "Baixar", "Publicar".

**Estados obrigatórios em todas as telas:** vazio, carregando (skeleton), sucesso, falha recuperável, sem créditos, arquivo inválido e conta de rede desconectada.

**Acessibilidade:** contraste AA, foco visível, editor operável por teclado (J/K/L e setas para navegar, I/O para marcar início e fim), rótulos em todos os controles.

**Identidade visual:** própria, sem imitar concorrentes. Tema escuro como padrão, com uma cor de destaque. Tokens de design definidos no código (cores, espaçamentos, raios, tipografia Inter).

## 6. Arquitetura

```
                 ┌────────────────────── Vercel ───────────────────────┐
 Navegador ────► │ Next.js (App Router, TS): UI + rotas /api (BFF)     │
   │             │  - autenticação (Supabase Auth)                     │
   │ upload      │  - autorização por organização                      │
   │ direto      │  - URLs assinadas, webhooks Asaas, OAuth das redes  │
   ▼             └───────┬──────────────────────────────┬──────────────┘
 Storage S3              │ SQL                          │ enfileira job
 (Cloudflare R2)         ▼                              ▼
   ▲             PostgreSQL (Supabase): dados + tabela `jobs` (fila)
   │                     ▲
   │                     │ SELECT … FOR UPDATE SKIP LOCKED
   │             ┌───────┴────────────────────────────────────────────┐
   └──────────── │ Workers Python em containers (pipeline do ClipForge)│
                 │  - worker-ingest: yt-dlp / ffprobe / proxy 720p    │
                 │  - worker-gpu: faster-whisper (GPU)                │
                 │  - worker-render: ffmpeg (CPU)                     │
                 │  - worker-publish: uploads para as redes           │
                 └──────────────┬─────────────────────────────────────┘
                                ▼
                     API do Claude (escolha dos cortes e textos)
```

### ADRs (decisões técnicas)

| # | Decisão | Motivo | Alternativa descartada |
|---|---|---|---|
| ADR-1 | **Frontend e API em Next.js + TypeScript**; workers continuam em **Python** | Reaproveita todo o pipeline já escrito (ffmpeg, Whisper, OpenCV são Python-first) | Reescrever o pipeline em Node: mais trabalho e bibliotecas de mídia piores |
| ADR-2 | **Fila na própria tabela `jobs` do Postgres** (SKIP LOCKED), com retries, backoff e timeout | Uma peça de infraestrutura a menos; transações atômicas entre job e créditos; volume do MVP é baixo | Redis + BullMQ: BullMQ é Node, e o worker é Python. Reavaliar acima de cerca de 50 jobs/min |
| ADR-3 | **Supabase** (Auth + Postgres), com acesso a dados **somente pelo servidor** e RLS como segunda camada | Auth pronta (link mágico, Google), Postgres gerenciado, backups | Auth própria: risco de segurança desnecessário |
| ADR-4 | **Cloudflare R2** para originais e renders, com regras de expiração automática | Compatível com S3 e **sem custo de saída** (download de vídeo é o maior tráfego) | AWS S3: saída cara |
| ADR-5 | **Transcrição por adaptador**: faster-whisper em GPU sob demanda (Modal ou RunPod) | Custo por hora de áudio muito menor que APIs pagas | API externa (Deepgram, AssemblyAI) como fallback do adaptador |
| ADR-6 | **Claude** para escolher cortes e escrever textos, com saída JSON estruturada | Já implementado e testado no formato. A heurística fica como fallback | — |
| ADR-7 | **Créditos em minutos de vídeo de origem** debitados no início da análise, com reserva → confirmação → estorno | Simples de entender; o custo real acompanha a duração | Cobrar por corte exportado: imprevisível para o usuário |
| ADR-8 | **Asaas por adaptador `PaymentGateway`** (assinaturas + webhooks) | Pix e boleto no Brasil; gateway substituível | — |
| ADR-9 | **Tokens OAuth das redes criptografados** (AES-GCM, chave no secret manager) | Tokens dão acesso de postagem à conta do cliente | — |

### Modelo de dados (resumo)

```
organizations(id, name, plan_id, asaas_customer_id, created_at)
memberships(org_id, user_id, role: owner|admin|editor)            -- MVP: só owner
projects(id, org_id, title, source_type: upload|youtube, source_url, source_key,
         proxy_key, duration_s, status, rights_confirmed_at, error, created_at, delete_after)
transcripts(project_id, language, segments jsonb)                 -- palavras com tempo
clips(id, project_id, start_s, end_s, hook_title, post_title, caption, hashtags[],
      score, reason, settings jsonb, render_key, thumb_key, render_status, updated_at)
jobs(id, org_id, type: ingest|transcribe|select|render|publish, payload jsonb,
     status: queued|running|done|failed, attempts, run_after, locked_by, locked_at,
     progress, stage, error, idempotency_key unique)
social_accounts(id, org_id, provider, external_id, display_name, token_enc, refresh_enc,
                expires_at, scopes, status)
publications(id, clip_id, social_account_id, status, external_id, url, error, created_at)
plans(id, name, price_cents, minutes_month, max_duration_s, watermark, max_storage_days)
subscriptions(id, org_id, plan_id, asaas_subscription_id, status, current_period_end)
credit_ledger(id, org_id, delta_minutes, kind: grant|reserve|consume|refund, ref_type, ref_id, created_at)
payment_events(id, provider_event_id unique, type, payload jsonb, processed_at)  -- idempotência
audit_log(id, org_id, actor_id, action, target, ip, created_at)
```

O saldo é sempre `SUM(credit_ledger)`, nunca um campo editável.

### Pipeline de jobs

1. `ingest`: baixa (yt-dlp) ou valida o upload (ffprobe) e gera um proxy 720p para o editor.
2. `transcribe`: Whisper com tempo por palavra.
3. `select`: Claude escolhe os cortes e cria os registros `clips`.
4. `render` (um por corte, em paralelo): o `render.py` atual, com marca d'água conforme o plano.
5. `publish`: um por corte e rede.

Cada etapa é idempotente (chave = projeto + etapa + versão das configurações) e grava `progress` e `stage`, que a UI lê por polling.

## 7. Segurança e LGPD

- Autorização no servidor em toda rota: o recurso precisa pertencer à organização do usuário. Testes negativos entre organizações fazem parte do CI.
- Upload só por URL assinada (15 min), com tamanho máximo na política. O worker valida com ffprobe e rejeita o resto.
- Download e preview por URL assinada curta (1 h). Bucket 100% privado.
- **SSRF:** o campo de link aceita só domínios do YouTube; yt-dlp roda com allowlist de extractors e sem acesso à rede interna.
- Workers em containers sem privilégios, com limites de CPU, memória e tempo por job. O ffmpeg roda com protocolos restritos (`-protocol_whitelist file`).
- Segredos (Claude, Asaas, chaves OAuth, chave de criptografia) só no servidor e no secret manager. Nada com prefixo `NEXT_PUBLIC_` além da URL pública do Supabase.
- Webhooks Asaas validados pelo token de autenticação e processados de forma idempotente (`payment_events`).
- Rate limit por usuário e IP em criação de projeto, login e publicação.
- **LGPD:**
  - Termos de uso e política de privacidade com aceite registrado.
  - Retenção padrão: original apagado em 7 dias (Gratuito) ou 30 dias (pagos); renders mantidos enquanto o projeto existir.
  - Exclusão de conta em até 30 dias, incluindo backups no próximo ciclo.
  - Exportação de dados em JSON.
  - Encarregado (DPO) indicado.
  - Subprocessadores listados: Supabase, Cloudflare, Vercel, Anthropic, provedor de GPU, Asaas.
- **Direitos autorais:** checkbox obrigatório "tenho direitos sobre este conteúdo", canal de denúncia e remoção, e suspensão de contas reincidentes.

## 8. Planos (proposta, a validar)

| Plano | Preço/mês | Minutos/mês | Duração máx. do vídeo | Marca d'água | Publicação nas redes |
|---|---|---|---|---|---|
| Gratuito | R$ 0 | 60 (única vez) | 30 min | sim | não |
| Criador | R$ 49 | 300 | 2 h | não | sim |
| Profissional | R$ 129 | 1.000 | 3 h | não | sim, mais prioridade na fila |

Minutos não usados não acumulam (MVP). Em falha de processamento, os créditos são estornados automaticamente.

## 9. Estimativa de custos (precisa de medição real)

Por **1 hora de vídeo de origem**, gerando cerca de 8 cortes de 45 s:

| Item | Estimativa |
|---|---|
| Transcrição faster-whisper large-v3 em GPU (cerca de 3 a 5 min de GPU) | US$ 0,05 a 0,15 |
| Claude (cerca de 20 mil tokens de entrada e 10 mil de saída, incluindo raciocínio) | US$ 0,30 |
| Render de 8 cortes em CPU (cerca de 10 a 15 min de vCPU) | US$ 0,03 a 0,08 |
| Storage R2 (cerca de 2 GB por 30 dias) e banco | US$ 0,03 |
| **Total** | **cerca de US$ 0,40 a 0,60 por hora**, ou cerca de R$ 0,05 por minuto |

Com essas premissas, o plano Criador (300 min) custaria cerca de R$ 15 em infraestrutura variável. **Esses números são estimativas**: a etapa 1 do roadmap inclui medi-los com vídeos reais.

**Custos fixos iniciais:**
- Vercel Pro: US$ 20/mês.
- Supabase Pro: US$ 25/mês.
- Servidor de render e publicação (VPS 4 vCPU): cerca de US$ 30/mês.
- GPU sob demanda: pago por uso.
- Total: cerca de US$ 80/mês mais o uso.

## 10. Riscos e dependências

| # | Risco | Impacto | Mitigação |
|---|---|---|---|
| R1 | **Download do YouTube a partir de servidores** é bloqueado com frequência (IPs de datacenter recebem "confirme que você não é um robô") e viola os Termos do YouTube, exceto para conteúdo próprio | Alto: é a entrada principal pedida | Upload de arquivo como caminho garantido; link do YouTube como opção "beta", com declaração de direitos, mensagem clara quando falhar e possibilidade de desligar. Avaliar proxy residencial só com orientação jurídica |
| R2 | **Aprovação das APIs das redes:** Google (verificação OAuth do escopo `youtube.upload` e auditoria para sair da cota baixa), TikTok (auditoria; antes dela os posts são só privados) e Meta (App Review de `instagram_content_publish`) | Alto: sem aprovação não há publicação pública | Iniciar os pedidos na **primeira semana**, com política de privacidade, termos, vídeo demonstrando o fluxo e domínio próprio. Até a aprovação: download e publicação manual |
| R3 | **TikTok Direct Post** exige regras de UX: mostrar o nome da conta, o usuário escolher a privacidade sem valor pré-selecionado, opções de comentário/dueto/stitch, declaração de conteúdo comercial e aviso de consentimento | Médio: reprovação na auditoria | Modal de publicação do TikTok seguindo as diretrizes oficiais. A publicação automática fica desligada para o TikTok |
| R4 | Custo de GPU e de IA fugir do controle | Médio | Créditos reservados antes do job, limite de concorrência por plano, orçamento diário com alerta, cache da transcrição |
| R5 | Qualidade do enquadramento (detector Haar simples) | Médio | Trocar por um detector moderno (YuNet/MediaPipe) e oferecer ajuste manual no editor (V1) |
| R6 | Conteúdo ilegal ou de terceiros enviado | Médio | Termos, declaração de direitos, denúncia e remoção, logs de auditoria |
| R7 | Licença de fontes e modelos | Baixo | Inter (OFL) e Whisper (MIT) são livres; revisar cada nova fonte |

**Dependências externas:** contas Supabase, Vercel, Cloudflare R2, Anthropic, Modal ou RunPod, Asaas, Google Cloud, TikTok for Developers, Meta for Developers, domínio próprio e e-mail transacional (Resend ou similar).

## 11. Plano de testes

- **Unitários (Python):** escolha de cortes, jump cuts e remapeamento de tempo, geração das legendas, cálculo do enquadramento.
- **Unitários (TypeScript):** créditos (reserva, consumo, estorno), regras de plano, validações.
- **Integração:** fila (concorrência, retry, timeout), storage (URL assinada, expiração), webhooks Asaas (aprovado, recusado, duplicado, atrasado, estorno, cancelamento, inadimplência) no sandbox do Asaas, OAuth das redes em contas de teste.
- **Autorização:** usuário da organização A tentando ler, editar, renderizar e publicar recursos da organização B em todas as rotas. Tudo deve ser negado.
- **E2E (Playwright):** cadastro → upload → processamento → editar corte → renderizar → baixar; e upgrade de plano com o sandbox do Asaas.
- **Mídia:** conjunto de vídeos autorizados com codecs (H.264, HEVC, VP9), proporções (16:9, 9:16, 4:3), durações (1 min a 2 h), sem áudio, áudio só em um canal e várias pessoas em cena.
- **Carga:** 20 projetos simultâneos, medindo tempo na fila e custo.
- **Acessibilidade:** axe no CI e navegação do editor só por teclado.
- **CI:** lint, typecheck, testes e build em todo PR. Staging separado da produção.

## 12. Roadmap de implementação

| Etapa | Entrega | Evidência de pronto |
|---|---|---|
| 0 | Contas nos provedores e **pedidos de aprovação nas redes** (rodam em paralelo) | Pedidos enviados |
| 1 | Monorepo (`web/` Next.js + `worker/` Python), banco com migrations, auth, organizações | Login funcionando em staging |
| 2 | Upload com URL assinada, fila em Postgres, worker ingest + transcribe + select | Vídeo real vira lista de cortes em staging; custo medido |
| 3 | Grade de cortes, editor com preview, worker render | MP4 baixado de staging, E2E passando |
| 4 | Planos, créditos e Asaas (sandbox) | Testes de webhook passando |
| 5 | Contas sociais e publicação | Post real em conta de teste de cada rede |
| 6 | LGPD (exclusão, exportação, retenção), termos, observabilidade, testes de carga | Checklist de release completo → beta fechado |

## 13. Decisões que dependem de você

1. Confirmar a stack: Next.js + Supabase + R2 + workers Python.
2. Entrada principal: upload garantido + link do YouTube em beta (R1)?
3. Nomes e preços dos planos (seção 8).
4. Nome e domínio do produto ("ClipForge" é provisório; checar se a marca e o domínio estão livres).
