# Guia do Usuário do BlindRSS

## Guia do Usuário do BlindRSS {#user-guide}

BlindRSS é um cliente de RSS e podcasts para desktop compatível com leitores de tela. Ele lê feeds RSS e Atom, reproduz anexos de podcasts e vídeos e funciona de forma independente ou com uma conta hospedada, como Miniflux, Inoreader, The Old Reader ou BazQux.

Este guia fica armazenado dentro do aplicativo, portanto funciona sem conexão com a internet e sem navegador. Pressione F1 em qualquer lugar do BlindRSS para abri-lo. Se o controle, diálogo, item de menu ou janela que você estiver usando tiver uma seção própria, F1 abrirá o guia nessa seção em vez do início.

Tudo aqui pode ser acessado pelo teclado. Use a lista de conteúdo para mover-se entre seções ou a caixa de pesquisa para encontrar uma palavra em qualquer parte do guia.

## Primeiros passos {#getting-started}

Quando o BlindRSS é iniciado pela primeira vez, ele não tem feeds. Há várias maneiras de adicionar alguns:

- Pressione Ctrl+N para adicionar um feed pelo endereço. Consulte Adicionando um feed.
- Pressione Ctrl+Shift+F para pesquisar diretórios de podcasts e feeds pelo nome. Consulte Encontrando podcasts e feeds RSS.
- Importe um arquivo OPML exportado de outro leitor. Consulte Importando OPML.
- Importe um arquivo do YouTube Takeout para assinar todos os canais que você já segue. Consulte Importando um arquivo do YouTube Takeout.
- Entre em uma conta hospedada em Ferramentas, Configurações, Provedor, e o BlindRSS lerá as assinaturas que já estão nessa conta. Consulte Contas on-line e provedores.

Depois de ter feeds, pressione F5 para atualizá-los. Novos artigos aparecem na lista de artigos, e as contagens de não lidos aparecem ao lado de cada feed na árvore.

Os três lugares que vale a pena visitar logo no início são Ferramentas, Configurações (como o BlindRSS se comporta), Ferramentas, Atalhos de teclado (todos os comandos e suas teclas) e este guia.

## A janela principal {#main-window}

A janela principal tem quatro regiões principais, além de uma barra de menus e uma barra de status. Tab e Shift+Tab movem-se entre elas, e F6 alterna os painéis na maioria dos gerenciadores de janelas.

- A árvore de feeds e pastas à esquerda.
- O campo de pesquisa acima da lista de artigos.
- A lista de artigos.
- O painel de leitura abaixo da lista de artigos.

A barra de menus contém Arquivo, Editar, Exibir, Reprodutor, Ferramentas e Ajuda. Pressione Alt para acessá-la e use as teclas de seta. Todos os itens de menu têm uma tecla de acesso em todos os idiomas da interface, e a barra de menus retorna ao começo nas duas extremidades.

Os tamanhos, o feed selecionado e o estado da janela são lembrados entre execuções. "Lembrar o último feed/pasta selecionado ao iniciar" em Configurações, Geral controla se o BlindRSS reabre no feed que você estava lendo por último.

## Lista de feeds e pastas {#feed-tree}

A árvore à esquerda lista seus feeds, as categorias que os agrupam, Pastas inteligentes, pesquisas salvas e as visualizações integradas (Todos os feeds, Favoritos, Artigos excluídos e Feeds com erros).

- As setas Para cima e Para baixo movem-se entre os itens.
- Seta para a direita expande uma categoria, Seta para a esquerda a recolhe.
- Enter ou selecionar um item carrega seus artigos na lista de artigos.
- F2 abre as propriedades do feed ou da categoria selecionada.
- A tecla Aplicações ou Shift+F10 abre o menu de contexto.

Cada feed mostra sua contagem de não lidos. Categorias expandidas e recolhidas são lembradas, portanto a árvore terá a mesma aparência na próxima vez que você iniciar.

Feeds que não puderam ser atualizados continuam listados normalmente; a visualização Feeds com erros os reúne, para que um feed que parou de funcionar silenciosamente não passe despercebido.

## Lista de artigos {#article-list}

A lista de artigos mostra os artigos do que estiver selecionado na árvore, depois de aplicados o Filtro de artigos atual, a ordem de classificação e o termo de pesquisa.

- As setas Para cima e Para baixo movem-se entre artigos; o painel de leitura acompanha.
- Enter abre o artigo selecionado.
- Shift+Up e Shift+Down estendem a seleção, permitindo que ações em massa funcionem em vários artigos ao mesmo tempo.
- Backspace alterna entre lido e não lido no artigo selecionado.
- Delete remove os artigos selecionados; Shift+Delete os remove sem a solicitação de confirmação.
- Ctrl+D adiciona ou remove um favorito.
- A tecla Aplicações ou Shift+F10 abre o menu de contexto.

Quais colunas aparecem, e em qual ordem, pode ser configurado globalmente e por feed. Consulte Colunas da lista de artigos.

## Painel de leitura {#reading-pane}

O painel de leitura abaixo da lista de artigos contém o texto do artigo selecionado. Ele é uma área de texto somente leitura, portanto um leitor de tela pode lê-lo linha por linha, palavra por palavra ou caractere por caractere, e o texto pode ser selecionado e copiado.

- Ctrl+F pesquisa no texto do artigo.
- F3 e Shift+F3 movem para a próxima e a ocorrência anterior.
- Enter em um link no texto abre esse link.

O modo como o texto é apresentado pode ser configurado em Configurações, Feeds e artigos: títulos podem ser anunciados, itens de lista marcados com marcadores e números, citações marcadas, links mostrados com seu endereço, tabelas descritas e texto alternativo de imagens incluído. O texto alternativo de imagens também pode ser forçado para ligado ou desligado em um feed pelo menu de contexto desse feed.

Se um feed publicar apenas um resumo curto, o BlindRSS poderá buscar o texto completo do artigo. Consulte Recuperação de texto completo de artigos.

## Janela de artigo {#article-window}

A abertura de um artigo pode colocá-lo em uma janela própria em vez de no painel de leitura, dando ao artigo toda a tela e mantendo-o aberto enquanto você prossegue na lista.

A janela é uma área de texto somente leitura com o mesmo comportamento de leitura, seleção e pesquisa no texto do painel de leitura. Escape a fecha.

## Campo de pesquisa {#search-field}

O campo de pesquisa acima da lista de artigos filtra a visualização atual enquanto você digita e confirma com Enter.

- Ctrl+E move o foco para o campo de pesquisa.
- Enter aplica o termo.
- Escape, ou o botão limpar, esvazia o campo e restaura a lista completa.

O campo de pesquisa pode ser ocultado se você nunca o usar; o menu Exibir tem o comando Mostrar/Ocultar campo de pesquisa. Se a pesquisa corresponde apenas a títulos ou a títulos e texto de artigos é definido em Configurações, Feeds e artigos, em "Correspondências da pesquisa".

Uma pesquisa que você quer manter pode ser transformada em uma pesquisa salva que permanece na árvore. Consulte Pesquisas persistentes.

## Barra de status {#status-bar}

A barra de status na parte inferior da janela principal tem três campos:

- Mensagens transitórias, como quantos artigos um filtro encontrou.
- Atividade em segundo plano, como uma atualização de feed ou um download em andamento.
- Status de reprodução: o que está sendo reproduzido e o tempo decorrido e restante.

Eles são deliberadamente separados para que uma mensagem de atualização não substitua uma contagem de resultados de pesquisa enquanto você a lê.

## Menus de contexto {#context-menus}

A árvore de feeds e a lista de artigos têm, cada uma, um menu de contexto, aberto com a tecla Aplicações ou Shift+F10. Eles contêm os comandos aplicáveis ao que estiver selecionado — atualizar, marcar como lido, editar, remover, copiar links, enfileirar mídia e assim por diante.

Menus de contexto também aceitam F1: com um item destacado, F1 abre a seção deste guia que o explica.

## Adicionando um feed {#adding-feeds}

Arquivo, Adicionar feed (Ctrl+N) assina um feed por endereço.

Cole ou digite o endereço do feed ou do próprio site — o BlindRSS procura um feed na página quando o endereço não é de um feed. Você também pode colar o endereço de um canal ou playlist do YouTube, um perfil do Mastodon ou Bluesky, uma comunidade PieFed ou Lemmy, uma página do SoundCloud ou Mixcloud, ou um endereço do Reddit ou Groups.io, e o BlindRSS o transforma em um feed.

Escolha a categoria em que o feed deve ficar ou deixe-o sem categoria. A opção "Abrir em visualização HTML" faz com que os artigos desse feed abram na visualização avançada por padrão.

Se você não souber o endereço, use Encontrando podcasts e feeds RSS.

## Detectando feeds em uma página {#detect-feeds}

Arquivo, Detectar feeds na página recebe o endereço de uma página comum e lista os feeds anunciados por ela, para que você possa assinar sem precisar procurar o link do feed por conta própria.

Este é o comando certo quando um site tem um link de "assinar" ou "RSS" que você não consegue acessar facilmente, ou quando a página oferece vários feeds (todas as publicações, uma categoria, comentários) e você quer escolher.

## Encontrando podcasts e feeds RSS {#find-podcast}

Ferramentas, Encontrar um podcast ou feed RSS (Ctrl+Shift+F) pesquisa diretórios de podcasts e feeds por nome, tópico ou endereço do site, para que você possa assinar sem conhecer nenhum endereço de feed.

1. Digite o que procura na caixa de pesquisa — o nome de um podcast, um tópico ou o endereço de um site.
2. Escolha uma fonte ou deixe em "Todas as fontes".
3. Pressione Enter ou o botão Pesquisar.
4. Percorra a lista de resultados com as setas. Cada linha mostra o título, de qual diretório ela veio e detalhes.
5. Pressione Enter em um resultado ou escolha OK para assiná-lo.

As pesquisas são executadas em vários diretórios de uma vez, e os resultados chegam conforme cada um responde, portanto a lista cresce enquanto você lê. Escape fecha o diálogo e interrompe a pesquisa.

## Diretórios de podcasts e feeds {#podcast-directories}

A caixa Fonte em Encontrar um podcast ou feed RSS escolhe onde pesquisar. Além de "Todas as fontes", "Todas as fontes de podcast" e "Todas as fontes de feed RSS", estes diretórios estão disponíveis individualmente:

- Diretórios de podcasts: iTunes (Apple Podcasts), gPodder, fyyd, Podverse, SoundCloud e Mixcloud.
- Diretórios de feeds: NewsBlur, Feedspot, Google News, Bing News e Feedly.
- Pesquisa de sites e comunidades: YouTube, Reddit, Groups.io e o Fediverse — Mastodon, Bluesky, PieFed e Lemmy ou Kbin, cada um também selecionável isoladamente.
- Descoberta por endereço: Feedsearch e a própria varredura de sites do BlindRSS, que busca um site e procura feeds nele.

Não se depende de um único diretório. A pesquisa em "Todas as fontes" consulta os grupos de podcasts e RSS juntos e mescla os resultados, mantendo feeds de consulta ampla do Google News abaixo das correspondências diretas de feeds.

## Assinando um resultado de pesquisa {#subscribing}

Em qualquer diálogo de pesquisa — Encontrar um podcast ou feed RSS, Pesquisa de vídeo ou o botão localizar do Arquivo de podcasts — pressionar Enter em um resultado, ou escolher OK com ele selecionado, assina-o.

O BlindRSS primeiro resolve o resultado para um endereço de feed real, portanto assinar um podcast encontrado em um diretório, um canal do YouTube ou uma conta do Fediverse funciona da mesma forma. O novo feed aparece na árvore e é atualizado imediatamente.

Se você o quiser em uma categoria específica, mova-o depois pelo menu de contexto ou pelas Propriedades do feed.

## Arquivo de podcasts {#podcast-archive}

Ferramentas, Arquivo de podcasts navega por todo o histórico de episódios de um podcast — tanto os episódios ainda presentes em seu feed quanto os mais antigos recuperados pelo BlindRSS — e os baixa em lotes.

Muitos feeds de podcasts publicam somente os episódios mais recentes. A recuperação de arquivo é executada automaticamente em segundo plano; esta janela é onde você vê seu status, tenta novamente manualmente e baixa o que ela encontrou.

- Escolha o podcast na caixa Podcast.
- Filtrar episódios restringe a lista enquanto você digita.
- Verificar novamente o arquivo executa a recuperação outra vez para esse podcast.
- Localizar ou adicionar podcast abre a pesquisa de feeds para que você possa arquivar um podcast que ainda não assina.
- Reproduzir toca o episódio selecionado, Baixar selecionado o baixa, e Baixar tudo baixa toda a lista visível.
- Cancelar downloads interrompe um lote em execução.

A janela permanece aberta enquanto um lote é baixado, para que você possa continuar lendo.

## Pesquisa de vídeo {#video-search}

Ferramentas, Pesquisa de vídeo pesquisa de uma vez todos os sites que o yt-dlp pode consultar e permite reproduzir, enfileirar ou assinar o que encontrar.

- Digite um termo de pesquisa e pressione Enter ou o botão Pesquisar.
- A caixa de escopo limita a pesquisa a um site; o padrão pesquisa todos eles.
- Os resultados chegam conforme cada site responde, primeiro os sites mais conhecidos. Títulos que chegam como espaços reservados são preenchidos à medida que são resolvidos.
- Carregar mais resultados busca outro lote de cada site.
- A classificação por um cabeçalho de coluna reordena o que já chegou.

Vídeos idênticos encontrados em vários sites são mesclados em uma linha. Sites adultos são excluídos, a menos que "Ativar sites adultos na pesquisa de vídeo" esteja ligado em Configurações, Avançado.

## Abrindo um artigo por URL {#open-article-url}

Arquivo, Abrir artigo recebe o endereço de qualquer página da web e a lê no BlindRSS como se fosse um artigo — texto extraído, no painel de leitura, com as mesmas opções de leitura de todo o resto.

Use-o para uma página avulsa que lhe enviaram, sem assinar nada. Se a página for um fórum ou discussão, o BlindRSS lê toda a conversa. Consulte Fóruns e tópicos de discussão.

## Abrindo uma URL de mídia {#open-media-url}

Arquivo, Abrir URL de mídia reproduz áudio ou vídeo de um endereço no reprodutor integrado sem assinar nada.

Ele aceita links diretos de mídia e endereços de páginas que o yt-dlp pode resolver — YouTube, Rumble, Odysee, SoundCloud e muitos outros. O resultado é reproduzido como qualquer outro item e pode ser adicionado à fila de reprodução.

## Removendo um feed {#removing-feeds}

Arquivo, Remover feed cancela a assinatura do feed selecionado. O mesmo comando está no menu de contexto do feed.

Remover um feed remove seus artigos do banco de dados. Isso não afeta nada que você já tenha baixado para o disco. Se você usa um provedor hospedado, o cancelamento também é enviado para essa conta.

Para remover uma categoria inteira e tudo que houver nela, use Excluir categoria e feeds no menu de contexto da categoria. Consulte Categorias e subcategorias.

## Propriedades do feed {#feed-properties}

F2 ou Editar feed no menu de contexto abre as propriedades do feed selecionado.

- Seu título, que você pode substituir; "Redefinir título para o padrão do feed" no menu de contexto restaura o título do próprio feed.
- Seu endereço e a categoria à qual pertence.
- Se novos artigos dele geram uma notificação.
- Se ele abre na visualização HTML avançada.
- Seu próprio layout de colunas da lista de artigos, na aba Cabeçalhos da lista, substituindo o global.

Ver descrição do feed no menu de contexto da lista de artigos mostra a descrição publicada pelo próprio feed.

## Categorias e subcategorias {#categories}

Categorias agrupam feeds na árvore e podem ser aninhadas: uma categoria pode conter feeds e outras subcategorias.

- Arquivo, Adicionar categoria cria uma.
- Adicionar subcategoria no menu de contexto de uma categoria cria uma dentro dela.
- Editar categoria a renomeia ou move. Consulte Propriedades da categoria.
- Remover categoria exclui a categoria, mas mantém seus feeds.
- Excluir categoria e feeds exclui a categoria e cancela a assinatura de tudo nela.
- Importar OPML aqui importa um arquivo diretamente para essa categoria.
- Exportar categoria para OPML exporta somente esse ramo.

Alguns provedores hospedados mantêm categorias em uma única lista plana. Quando é o caso, o BlindRSS informa isso e as opções de "mover para a categoria pai" não ficam disponíveis.

## Propriedades da categoria {#category-properties}

Editar categoria abre as propriedades da categoria: seu nome e a categoria pai em que ela está.

Renomear uma categoria mantém todos os seus feeds. Movê-la move todo o ramo, inclusive as subcategorias.

## Atualizando feeds {#refreshing}

- F5 atualiza todos os feeds.
- Ctrl+F5 atualiza somente o feed ou a categoria selecionada.
- Shift+F5 interrompe uma atualização em execução.
- Atualizar categoria no menu de contexto de uma categoria atualiza esse ramo.

Somente um entre Atualizar feeds e Parar atualização fica disponível por vez, portanto o comando de teclado corresponde ao que o menu oferece. O progresso aparece no segundo campo da barra de status.

A atualização automática é configurada em Configurações, Feeds e artigos: o intervalo, quantos feeds são atualizados de uma vez, quantas conexões por host, o tempo limite por feed e quantas vezes um feed com falha é tentado novamente. "Atualizar feeds automaticamente ao iniciar" atualiza tudo na inicialização, e a opção de carga de trabalho de inicialização escolhe entre usar o cache e forçar uma atualização completa.

## Feeds com erros {#feed-errors}

A visualização Feeds com erros e Arquivo, Ver erros de feeds listam os feeds cuja última atualização falhou, com o motivo.

Um feed que parou de funcionar silenciosamente parece exatamente igual a um feed sem artigos novos, por isso essa visualização existe. A partir dela, você pode:

- Atualizar selecionado, para tentar novamente agora.
- Copiar detalhes, para colocar o texto do erro na área de transferência.
- Propriedades do feed, para corrigir o endereço.
- Remover feed, quando o feed tiver desaparecido definitivamente.

Causas comuns são um feed movido ou descontinuado, um site que agora exige verificação no navegador (consulte Importando cookies do site) e uma indisponibilidade temporária do servidor.

## Importando OPML {#import-opml}

OPML é o formato de arquivo padrão para uma lista de assinaturas de feeds. Todo leitor de feeds pode exportar um, portanto o OPML é como você move suas assinaturas de outro leitor para o BlindRSS sem adicioná-las uma por uma.

Arquivo, Importar OPML pede o arquivo e adiciona todos os feeds nele, mantendo a estrutura de categorias descrita pelo arquivo. Feeds que você já assina não são duplicados.

Importar OPML aqui, no menu de contexto de uma categoria, coloca toda a importação dentro dessa categoria em vez de no nível superior.

Para obter um arquivo OPML de outro leitor, procure por "Exportar", "Backup" ou "Assinaturas" nas configurações dele.

## Exportando OPML {#export-opml}

Arquivo, Exportar OPML grava todas as suas assinaturas, com suas categorias, em um arquivo OPML.

Use-o para fazer backup das assinaturas, movê-las para outro leitor ou computador ou compartilhar um conjunto de feeds com outra pessoa. Exportar categoria para OPML no menu de contexto de uma categoria exporta apenas esse ramo.

## Importando um arquivo do YouTube Takeout {#import-youtube-takeout}

O Google Takeout é o serviço de exportação de dados do Google. Um arquivo do YouTube Takeout é um arquivo ZIP contendo seus dados do YouTube, incluindo a lista de canais que você assina. Arquivo, Importar YouTube Takeout lê esse ZIP e assina esses canais como feeds, para que os novos vídeos de cada canal cheguem como artigos.

Para obter o arquivo:

1. Vá para takeout.google.com e entre com a conta do Google na qual estão suas assinaturas do YouTube.
2. Escolha "Desmarcar tudo" e selecione somente YouTube e YouTube Music.
3. Em "Todos os dados do YouTube incluídos", mantenha pelo menos "assinaturas"; "histórico" e "playlists" são opcionais, e o BlindRSS também pode usá-los.
4. Exporte uma vez como arquivo ZIP e espere o e-mail do Google — um arquivo grande pode levar horas.
5. Baixe o ZIP e indique-o para este comando.

O BlindRSS então mostra o que encontrou, agrupado por fonte, e permite escolher quais grupos importar:

- Assinaturas: os canais que você segue.
- Histórico: canais que você assistiu, mas não segue.
- Seus próprios canais.
- Playlists, como feeds próprios.

Endereços duplicados são removidos, portanto importar outro arquivo mais tarde adiciona apenas o que for novo. O ZIP nunca é descompactado no disco; somente os pequenos arquivos de dados dentro dele são lidos.

## Pesquisas persistentes {#persistent-search}

Uma pesquisa persistente é um termo de pesquisa que permanece na árvore como seu próprio item, para que os artigos que correspondem a ela estejam sempre a uma tecla de seta de distância.

Ferramentas, Configurar pesquisa persistente gerencia a lista: Adicionar cria uma a partir de um termo, Remover a exclui. Cada pesquisa salva aparece na árvore e é reavaliada sempre que você a seleciona, portanto sempre reflete os artigos atuais.

Use-a para um assunto que você acompanha em todos os feeds — o nome de uma pessoa, um produto, um lugar. Para algo mais estruturado que uma frase, use Pastas inteligentes.

## Pastas inteligentes {#smart-folders}

Uma Pasta inteligente é uma pasta na árvore cujo conteúdo é definido por uma regra, e não pelo feed de onde um artigo veio.

Nova Pasta inteligente, no menu de contexto da árvore, abre o editor de regras. Uma regra é um conjunto de condições unidas por "corresponder a todas" (e) ou "corresponder a qualquer" (ou), e grupos de condições podem ser aninhados, portanto "(A e B) ou C" pode ser expresso.

As condições testam estes campos:

- Campos sim/não: lido, favorito, aberto, atualizado.
- Campos de texto: título, conteúdo, descrição, autor, feed, url e tag — as categorias ou tags que o próprio site publica.

Condições de texto usam contém, não contém, é igual a ou começa com.

Pastas inteligentes nunca movem nem copiam nada; elas são uma visualização dos artigos que você já tem. Para alterar artigos à medida que chegam, use Regras de filtro.

## Regras de filtro {#filter-rules}

Ferramentas, Regras de filtro é o mecanismo de classificação de artigos do BlindRSS. As regras são executadas sobre artigos recebidos da mesma forma que filtros de e-mail são executados sobre mensagens recebidas.

Cada regra associa uma condição — o mesmo editor de regras usado pelas Pastas inteligentes — a um conjunto de ações:

- Mover o artigo para uma categoria.
- Também rotulá-lo com uma categoria, deixando-o onde está.
- Marcá-lo como lido.
- Marcá-lo como favorito.
- Excluí-lo, seguindo o comportamento de exclusão configurado.
- Ignorar sua notificação de novo artigo.

As regras são executadas na ordem da lista, e cada regra ativada que corresponde contribui com suas ações. Uma regra marcada para parar encerra o processamento para esse artigo depois de corresponder, portanto regras posteriores nunca o veem. Mova regras para cima e para baixo para controlar qual vence.

Uma regra sem ações não faz nada e é rejeitada, portanto uma regra incompleta não pode engolir artigos silenciosamente.

## Filtro de artigos {#article-filter}

Exibir, Filtro de artigos limita todas as visualizações pelo estado de leitura e pela presença de mídia anexada a um artigo. Os dois grupos são combinados.

- Ctrl+1: todos os artigos.
- Ctrl+2: somente não lidos.
- Ctrl+3: somente lidos.
- Ctrl+4: mídia e não mídia.
- Ctrl+5: somente com mídia.
- Ctrl+6: somente sem mídia.

O filtro se aplica ao que estiver selecionado na árvore, incluindo Pastas inteligentes e pesquisas salvas, e persiste entre execuções. "Somente com mídia" é a forma mais rápida de transformar um feed misto em uma lista de podcasts.

## Classificando artigos {#sorting}

Exibir, Classificar por ordena a lista de artigos por data, nome, autor, descrição, feed ou status. Crescente alterna a direção; o padrão é do mais novo para o mais antigo.

A classificação se aplica a todas as visualizações e é lembrada entre execuções. Classificar por feed é útil em Todos os feeds e em Pastas inteligentes, onde artigos vêm de muitas fontes de uma vez.

## Colunas da lista de artigos {#list-headers}

As colunas da lista de artigos, sua ordem e suas larguras são suas para escolher. Configurações, Cabeçalhos da lista define o layout global; a própria aba Cabeçalhos da lista de um feed o substitui para esse feed, e "Usar o layout global de colunas" desliga a substituição novamente.

Menos colunas significam menos conteúdo para um leitor de tela ler em cada linha, portanto vale a pena remover as que você nunca usa.

## Abrindo artigos {#opening-articles}

Enter em um artigo na lista o abre. Dependendo do artigo e das suas configurações, isso significa o painel de leitura, uma janela própria ou a visualização HTML avançada.

- Abrir artigo no menu de contexto faz o mesmo.
- Abrir no navegador passa o endereço do artigo para o navegador web do sistema.
- Abrir navegador acessível lê a página dentro do BlindRSS. Consulte Navegador acessível.

Abrir um artigo o marca como lido, a menos que você tenha alterado esse comportamento.

## Artigos lidos e não lidos {#read-status}

- Backspace, ou Alternar lido/não lido, alterna o artigo selecionado.
- Ctrl+Shift+R marca tudo na visualização atual como lido.
- Marcar todos os itens como lidos, no menu de contexto de um feed ou categoria, faz o mesmo para esse ramo.
- Marcar como lido e Marcar como não lido no menu de contexto da lista de artigos agem sobre toda a seleção e dizem quantos artigos afetarão.

As contagens de não lidos aparecem ao lado de cada feed na árvore. O Filtro de artigos pode ocultar artigos lidos completamente.

## Favoritos {#favorites}

Ctrl+D adiciona o artigo selecionado aos Favoritos ou o remove se ele já estiver lá. A visualização Favoritos na árvore lista tudo que você marcou.

Favoritos sobrevivem à política de retenção: um artigo que você favoritou não é removido quando artigos mais antigos são limpos. Favorito também pode ser usado como condição em Pastas inteligentes e Regras de filtro.

## Artigos excluídos {#deleted-articles}

O que Delete faz pode ser configurado em Configurações, Geral, em "Quando eu excluo um artigo":

- Movê-lo para Artigos excluídos, onde ele pode ser restaurado.
- Removê-lo permanentemente.
- Movê-lo para uma categoria que você nomear.

Com a primeira configuração, a visualização Artigos excluídos na árvore lista o que você removeu, Restaurar devolve um artigo e excluí-lo dentro dessa visualização o remove definitivamente.

"Confirmar antes de excluir artigos" controla a solicitação de confirmação. Shift+Delete sempre a ignora.

## Recuperação de texto completo de artigos {#full-text}

Muitos feeds publicam somente uma manchete e uma frase ou duas. O BlindRSS pode buscar a página do artigo e extrair o texto real, para que o painel de leitura mostre o artigo inteiro em vez de uma prévia.

Isso acontece automaticamente, em segundo plano, conforme você percorre a lista, e o resultado é armazenado em cache. "Armazenar texto completo em cache em segundo plano" em Configurações, Feeds e artigos pré-busca os artigos próximos de sua posição para que descer a lista não espere pela rede.

Se um site se recusar completamente a ser lido, geralmente ele está atrás de uma verificação no navegador. Consulte Importando cookies do site.

## Visualização avançada de texto completo {#rich-view}

Ctrl+Shift+H alterna o painel de leitura para a visualização HTML avançada, que renderiza o artigo como um navegador faria, com títulos, listas, tabelas e links como elementos reais pelos quais um leitor de tela pode navegar usando seus próprios comandos estruturais.

A visualização de texto simples é o padrão porque é mais rápida e nunca surpreende você. A visualização avançada vale a pena para artigos cuja estrutura transmite significado.

Um feed pode ser configurado para sempre abrir na visualização avançada pelas Propriedades do feed, e links na visualização avançada abrem no navegador do sistema em vez de dentro da visualização.

## Navegador acessível {#accessible-browser}

Exibir, Abrir navegador acessível abre uma página dentro do BlindRSS em uma janela criada para leitura por leitores de tela, em vez de passá-la ao navegador do sistema.

É a ferramenta certa para uma página que precisa ser lida em vez de utilizada interativamente, e para sites cuja própria interface é difícil de navegar. Ele compartilha as configurações de cookies e de identificação do navegador do BlindRSS, portanto páginas atrás de uma verificação de navegador também abrem aqui depois que você importar cookies para elas.

## Vídeos do YouTube {#youtube}

Um endereço de canal ou playlist do YouTube pode ser assinado como qualquer feed. Seus vídeos então chegam como artigos, com a descrição, a transcrição e a lista de capítulos em linha, para que um vídeo possa ser lido em vez de assistido.

A reprodução passa pelo yt-dlp. Configurações, YouTube o controla:

- Um arquivo de cookies, que permite ao BlindRSS ver vídeos com restrição de idade e apenas para membros aos quais você tem acesso. Ele pode ser importado diretamente de um navegador ou obtido automaticamente de exportações cookies.txt na sua pasta Downloads.
- "Reproduzir YouTube baixando primeiro", que demora mais para iniciar e é muito mais confiável.
- A pasta de cache de reprodução e seu tamanho máximo, com um botão para limpá-la.

Importar YouTube Takeout assina todos os canais que você já segue em uma etapa.

## Fóruns e tópicos de discussão {#forums}

Reddit, Lemmy, Groups.io e Google Groups são lidos como conversas inteiras em vez de uma publicação por vez: abrir uma discussão fornece a você a publicação original e as respostas em uma peça contínua de texto, muito mais rápida de ler do que acompanhar uma conversa no navegador.

Assinar funciona como em qualquer feed — cole o endereço do subreddit, comunidade ou grupo. Repositórios do GitHub são suportados da mesma maneira, assim como contas e comunidades do Mastodon, Bluesky e PieFed.

## Recortar, copiar e colar {#clipboard}

O menu Editar contém os comandos padrão da área de transferência — Recortar (Ctrl+X), Copiar (Ctrl+C), Colar (Ctrl+V) e Selecionar tudo (Ctrl+A) — e eles funcionam em todos os campos de texto e no painel de leitura.

O BlindRSS adiciona comandos que copiam coisas que ele conhece:

- Copiar link, o endereço do artigo.
- Copiar link de mídia, o endereço de seu áudio ou vídeo.
- Copiar texto, o texto do artigo conforme lido no painel de leitura.
- Copiar URL do feed, o endereço do feed selecionado.
- Copiar link de imagem, em um artigo com imagem.

## O reprodutor integrado {#player}

O BlindRSS reproduz internamente anexos de podcasts e vídeos, por meio do VLC, portanto a reprodução nunca deixa o aplicativo. Ctrl+Shift+P mostra ou oculta a janela do reprodutor, e a reprodução continua de qualquer forma.

A reprodução é suavizada por um proxy de cache local de intervalos, por isso buscar uma posição em um episódio longo é rápido mesmo em conexão lenta. Fluxos que precisam ser resolvidos — YouTube, Rumble, Odysee — passam primeiro pelo yt-dlp.

"Mostrar a janela do reprodutor ao iniciar a reprodução" em Configurações, Reprodutor de mídia decide se a janela aparece sozinha quando algo começa.

## Controles do reprodutor {#player-controls}

A janela do reprodutor contém, na ordem de tabulação: o status de reprodução, o controle deslizante de posição, o tempo decorrido e total, botões de retroceder e avançar, a caixa de velocidade, o botão de capítulos e o controle deslizante de volume. Todos podem ser alcançados e operados pelo teclado, e cada um anuncia seu valor atual.

- Ctrl+P reproduz e pausa.
- Ctrl+S para.
- Ctrl+Left e Ctrl+Right retrocedem e avançam rapidamente, e repetem enquanto mantidos. No macOS, Option+Left e Option+Right fazem o mesmo, porque Ctrl+Left e Ctrl+Right pertencem ao Mission Control nele.
- Ctrl+Up e Ctrl+Down alteram o volume.

As teclas de busca e volume funcionam de qualquer lugar no BlindRSS enquanto algo está sendo reproduzido, inclusive dentro de um diálogo, portanto você nunca precisa encontrar a janela do reprodutor para pausar.

## Atalhos de teclado do reprodutor {#player-shortcuts}

- Ctrl+Shift+P: mostrar ou ocultar a janela do reprodutor.
- Ctrl+P: reproduzir ou pausar.
- Ctrl+S: parar.
- Ctrl+Left e Ctrl+Right: retroceder e avançar rapidamente (Option+Left e Option+Right no macOS).
- Ctrl+Up e Ctrl+Down: aumentar e diminuir o volume.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: mais rápido, mais lento, voltar à velocidade normal.
- Ctrl+Shift+E: o equalizador.
- Ctrl+Shift+C: a fila de reprodução.
- Ctrl+Shift+T e Ctrl+Shift+V: próximo e anterior na fila.

Todos eles podem ser remapeados em Ferramentas, Atalhos de teclado. Os comandos de velocidade usam deliberadamente letras por padrão em vez de Ctrl+Shift+digit ou Ctrl+Shift+period, porque o Windows e alguns complementos do NVDA os capturam antes que qualquer aplicativo os veja.

## Velocidade de reprodução {#playback-speed}

Reprodutor, Velocidade de reprodução altera a rapidez com que a mídia é reproduzida, de meia velocidade a velocidade tripla, preservando o tom.

- Ctrl+Shift+U acelera, Ctrl+Shift+D desacelera, Ctrl+Shift+N retorna a 1x.
- O submenu tem etapas fixas: 0.5x, 0.75x, 1x, 1.25x, 1.5x, 1.75x, 2x, 2.5x e 3x.
- A janela do reprodutor tem uma caixa de velocidade que você pode definir diretamente.

"Velocidade de reprodução padrão" em Configurações, Reprodutor de mídia define a velocidade com que tudo começa.

## Equalizador {#equalizer}

Ctrl+Shift+E, ou Reprodutor, Equalizador, abre um equalizador de dez bandas com pré-amplificador.

- "Ativar equalizador" liga e desliga tudo.
- Cada banda é um controle deslizante que anuncia seu ganho conforme você o altera.
- Salvar como predefinição armazena as bandas atuais sob um nome; Excluir predefinição remove uma.
- Redefinir (Plano) retorna todas as bandas a zero.

O equalizador se aplica a tudo que o BlindRSS reproduz, e sua configuração é lembrada.

## Capítulos {#chapters}

Podcasts e vídeos do YouTube geralmente trazem capítulos. Quando o item em reprodução os tem, Reprodutor, Capítulos os lista, e ir para um busca essa posição.

- O submenu de capítulos é preenchido assim que os capítulos do item são conhecidos e diz "Nenhum capítulo disponível" quando ele não tem nenhum.
- A janela do reprodutor tem um botão de capítulos e uma caixa de capítulos.
- Links de capítulos, no menu de contexto da lista de artigos, lista os links contidos na descrição de um capítulo.

Os capítulos são carregados em segundo plano conforme você percorre a lista, portanto geralmente estão prontos antes de você pressionar reproduzir.

## Fila de reprodução {#play-queue}

A fila de reprodução é a lista do que será reproduzido a seguir.

- Ctrl+Shift+C abre a janela da fila.
- Ctrl+Shift+T e Ctrl+Shift+V reproduzem o próximo e o item anterior.
- Adicionar à fila de reprodução e Remover da fila de reprodução, no menu de contexto da lista de artigos, alteram-na.

Na janela da fila, Reproduzir inicia o item selecionado, Mover para cima e Mover para baixo reordenam a fila, Remover elimina um item e Limpar tudo esvazia a fila. A fila sobrevive a reinicializações.

## Transmitindo para outros dispositivos {#casting}

O BlindRSS pode enviar o que reproduz para um dispositivo em sua rede: Chromecast, alto-falantes AirPlay, renderizadores DLNA/UPnP, alto-falantes Sonos, reprodutores Roku e Kodi. Um episódio continua no dispositivo de onde estava, e pausar, avançar ou voltar e a posição funcionam lá como localmente (o Roku não permite avançar ou voltar).

Escolha o dispositivo no diálogo de transmissão; o BlindRSS transmite por seu próprio proxy local, portanto um dispositivo que não pode buscar o endereço original por si só ainda reproduz o item. Os controles de transporte continuam funcionando a partir do BlindRSS enquanto ele transmite.

## Pular silêncio {#silence-skipping}

"Pular silêncio (experimental)" em Configurações, Reprodutor de mídia detecta trechos silenciosos durante a reprodução e os pula, o que encurta perceptivelmente podcasts falados com pausas longas.

Ele analisa o áudio enquanto é reproduzido, portanto consome alguma CPU e é marcado como experimental. Desligue-o se a reprodução não estiver fluida.

## Baixando mídia {#downloads}

- Baixar salva o áudio ou vídeo do artigo selecionado em seu formato padrão.
- Baixar como permite escolher primeiro o formato.

Os downloads devem ser ativados com "Ativar downloads" em Configurações. A pasta de download, a política de retenção e o formato padrão de download de vídeo são definidos na mesma página; a pasta padrão é a pasta Downloads do sistema.

O progresso aparece no segundo campo da barra de status, e itens baixados são reproduzidos do disco depois, em vez da rede. O Arquivo de podcasts pode baixar todo o catálogo anterior de um podcast em um lote.

## Configurações {#settings}

Ferramentas, Configurações (Ctrl+comma) contém todas as opções, em abas: Geral, Feeds e artigos, YouTube, Reprodutor de mídia, Provedor, Notificações, Traduzir, Cabeçalhos da lista, Avançado e Solução de CAPTCHA.

Ctrl+Tab e Ctrl+Shift+Tab movem-se entre abas; Tab move-se pelos controles da aba atual. OK aplica tudo, Cancelar descarta tudo. As posições das abas são mantidas estáveis entre versões, porque se tornam memória muscular.

Pressionar F1 em uma aba abre a seção dessa aba neste guia.

## Configurações: Geral {#settings-general}

- Idioma da interface e se o BlindRSS segue o idioma do sistema. Uma alteração entra em vigor ao reiniciar. Consulte Idioma da interface.
- "Lembrar o último feed/pasta selecionado ao iniciar".
- "Confirmar antes de excluir artigos" e o que a exclusão faz — mover para Artigos excluídos, excluir permanentemente ou mover para uma categoria que você nomear.
- "Modo de depuração (mostrar console ao iniciar)", que também grava um blindrss.log rotativo ao lado de seus dados.
- Inicialização e bandeja: fechar para a bandeja, minimizar para a bandeja, iniciar na bandeja, sempre iniciar maximizado e verificar atualizações ao iniciar.

## Configurações: Feeds e artigos {#settings-feeds}

- O intervalo de atualização automática, de cinco minutos a quatro horas.
- Se a pesquisa corresponde somente a títulos ou a títulos e texto de artigos.
- Máximo de atualizações simultâneas, máximo de conexões por host, o tempo limite do feed e quantas vezes um feed com falha é tentado novamente.
- Máximo de visualizações em cache e "Armazenar texto completo em cache em segundo plano".
- "Atualizar feeds automaticamente ao iniciar" e a carga de atualização de inicialização: usar o cache, atualizar completamente na inicialização ou sempre atualizar completamente.
- Retenção de artigos, que decide por quanto tempo artigos são mantidos. Favoritos nunca são removidos pela retenção.
- Como o texto do artigo é apresentado: anunciar títulos, marcar itens de lista com marcadores e números, marcar citações, mostrar links com seu endereço, descrever tabelas e incluir texto alternativo de imagens.

## Configurações: YouTube {#settings-youtube}

- O arquivo de cookies do yt-dlp, com um botão Procurar, um botão "Importar do navegador" e uma opção para obter automaticamente exportações cookies.txt da pasta Downloads.
- Ler cookies diretamente de um navegador instalado.
- "Reproduzir YouTube baixando primeiro", que inicia mais lentamente, mas é a opção mais confiável.
- A pasta de cache de reprodução do YouTube, seu tamanho máximo em megabytes e um botão para limpá-la agora.

Cookies são o que torna reproduzíveis vídeos com restrição de idade e apenas para membros, e são o que um erro "entre para confirmar que você não é um bot" está pedindo.

## Configurações: Reprodutor de mídia {#settings-media-player}

- A placa de som preferida ou o padrão do sistema.
- "Pular silêncio (experimental)". Consulte Pular silêncio.
- A velocidade de reprodução padrão.
- "Mostrar a janela do reprodutor ao iniciar a reprodução".
- O tamanho do cache de rede em milissegundos, que troca atraso de inicialização por resiliência em conexão lenta.
- Caminhos para ffmpeg, ffprobe e yt-dlp. Deixe um em branco para detecção automática; um caminho que você definir substitui a detecção, e o que foi detectado é exibido ao lado de cada um.
- Downloads: se downloads estão ativados, a pasta de download, a política de retenção e o formato padrão de download de vídeo.
- Sons: se o BlindRSS reproduz seus sons de notificação.

## Configurações: Provedor {#settings-provider}

Escolhe onde suas assinaturas ficam: localmente no BlindRSS ou em uma conta hospedada. Consulte Contas on-line e provedores para saber o que cada um precisa.

A página mostra qual provedor está ativo e as credenciais dele — um endereço e uma chave de API do Miniflux, um ID e uma chave de aplicativo do Inoreader com um botão Autorizar, ou um endereço de e-mail e senha para The Old Reader ou BazQux. Limpar autorização desconecta uma conta Inoreader.

O provedor local usa os feeds que você adiciona dentro do aplicativo com Adicionar feed e Importar OPML.

## Configurações: Notificações {#settings-notifications}

- "Ativar notificações para novos artigos" e se o nome do feed aparece no texto da notificação.
- O número máximo de notificações por atualização e se uma notificação de resumo é exibida quando esse limite é alcançado.
- Testar notificação envia uma agora.
- Excluir feeds escolhe feeds que nunca notificam.
- Anúncios: quais eventos o BlindRSS fala diretamente ao leitor de tela, por evento, com um botão Testar anúncio que envia um teste tanto por fala quanto por Braille.

## Configurações: Traduzir {#settings-translate}

Ativa a tradução automática de conteúdo de artigos e escolhe o serviço que a realiza.

- "Ativar tradução automática para conteúdo de artigos".
- O provedor: Grok (xAI), Groq, OpenAI, OpenRouter, Gemini ou Qwen.
- O idioma de destino, escolhido na lista ou digitado como código, como en, es, fr ou pt-BR.
- Uma chave de API para o provedor escolhido e, opcionalmente, um modelo específico. Para OpenRouter, "Carregar modelos do OpenRouter" busca a lista de modelos disponível.

Grok e Groq são serviços diferentes, com nomes confusamente parecidos: Grok é da xAI, com chaves de console.x.ai que começam com "xai-"; Groq hospeda LLaMA e Mistral, com chaves gratuitas de console.groq.com que começam com "gsk_".

Isto traduz texto de artigos. Para alterar o idioma da própria interface do BlindRSS, consulte Idioma da interface.

## Configurações: Cabeçalhos da lista {#settings-list-headers}

Define o layout global de colunas da lista de artigos: quais colunas aparecem, em qual ordem e com qual largura. Consulte Colunas da lista de artigos.

Um feed individual pode substituir isso em suas próprias Propriedades do feed.

## Configurações: Avançado {#settings-advanced}

- Local de armazenamento de dados: mantenha seu banco de dados e configurações na pasta de dados do usuário ou na pasta do aplicativo, com ambos os caminhos exibidos. A opção de pasta do aplicativo é o que torna uma instalação portátil.
- Atualizações: "Instalar atualizações automaticamente sem confirmação".
- Identificação do navegador: com qual navegador o BlindRSS se identifica ao buscar feeds ou uma cadeia User-Agent personalizada que você digitar. A cadeia efetiva é mostrada abaixo. Isso importa para sites que bloqueiam clientes desconhecidos.
- Pesquisa de vídeo: "Ativar sites adultos na pesquisa de vídeo", desativado por padrão.

## Configurações: Solução de CAPTCHA {#settings-captcha}

Uma rota opcional, paga e de último recurso para sites que respondem com um CAPTCHA que cookies importados não conseguem superar.

"Ativar serviço de solução de CAPTCHA" o liga, e o campo de chave de API contém a chave de sua conta no serviço de solução. Há taxas por solução, por isso ele fica desativado por padrão e só é tentado depois que tudo mais falhar.

Tente primeiro Importando cookies do site; é gratuito e resolve a maioria dos casos.

## Contas on-line e provedores {#providers}

O BlindRSS pode manter suas próprias assinaturas ou lê-las de uma conta hospedada. Configurações, Provedor escolhe qual.

- Local: as assinaturas ficam no banco de dados do próprio BlindRSS neste computador. Nada é sincronizado em nenhum lugar.
- Miniflux: precisa do endereço do seu servidor Miniflux e de uma chave de API nas configurações da sua conta Miniflux.
- Inoreader: precisa de um ID de aplicativo e uma chave de aplicativo na página de desenvolvedor do Inoreader, e depois do botão Autorizar para entrar.
- The Old Reader: precisa do endereço de e-mail e senha da sua conta.
- BazQux: precisa do endereço de e-mail e senha da sua conta.

Com um provedor hospedado, o estado de leitura, as assinaturas e as categorias pertencem à conta, portanto acompanham você em qualquer outro dispositivo conectado à mesma conta. Alguns provedores mantêm categorias em uma única lista plana, e o BlindRSS informa isso em vez de oferecer aninhamento que não persistiria.

## Notificações {#notifications}

O BlindRSS gera uma notificação do sistema quando chegam artigos novos, sujeito a Configurações, Notificações.

- Notificações podem ser desativadas completamente.
- O nome do feed pode ser incluído no texto.
- Um limite restringe quantas chegam por atualização, com uma notificação de resumo opcional quando o limite é alcançado.
- Feeds individuais podem ser excluídos, tanto em Excluir feeds nas Configurações quanto em "Notificações para este feed" no menu de contexto do feed.
- Uma Regra de filtro pode suprimir a notificação dos artigos aos quais corresponde.

Separadamente, Anúncios falam eventos escolhidos diretamente ao leitor de tela por meio da própria interface do NVDA ou JAWS e por Braille, que chega mesmo quando uma notificação do sistema não chega.

## Tradução de artigos {#translation}

Com a tradução ativada em Configurações, Traduzir, o texto do artigo é traduzido para seu idioma de destino enquanto você o lê, usando o serviço de IA configurado.

A tradução acontece sob demanda e é armazenada em cache, portanto reler um artigo não paga por ela duas vezes. Ela precisa de uma conexão com a internet e de sua própria chave de API para o serviço escolhido.

A interface do aplicativo é traduzida separadamente, por meio de seus próprios catálogos. Consulte Idioma da interface.

## Importando cookies do site {#site-cookies}

Alguns sites colocam uma página de verificação de navegador — tipicamente um desafio do Cloudflare de "verificando seu navegador" — na frente de seu conteúdo. Esses sites só respondem a uma sessão que já passou pelo desafio em um navegador real, portanto o BlindRSS não consegue buscá-los sozinho.

Ferramentas, Importar cookies do site fornece a ele essa sessão:

1. Abra o site no navegador e espere que termine de carregar.
2. Exporte seus cookies para um arquivo cookies.txt com uma extensão de navegador cookies.txt. Para navegadores baseados em Chrome, o diálogo cria um link para "Obter cookies.txt LOCALMENTE".
3. Escolha o arquivo exportado no diálogo.
4. Cole a cadeia User-Agent do navegador no campo abaixo. Pesquisar na web por "qual é meu user agent" a mostra. O Cloudflare exige o User-Agent exato para o qual o cookie foi emitido, portanto isso importa.

Navegadores da família Firefox têm um caminho de um clique: "Importar do navegador" lê diretamente seu banco de dados de cookies. Navegadores baseados em Chromium criptografam os deles, por isso precisam da extensão.

## Atalhos de teclado {#keyboard-shortcuts}

Ferramentas, Atalhos de teclado lista todos os comandos do BlindRSS, agrupados por categoria, com sua tecla atual, e permite alterar qualquer um deles.

- Selecione um comando e escolha Alterar atalho. O diálogo de captura então registra a próxima combinação de teclas que você pressionar.
- Remover atalho deixa um comando sem associação; ele ainda funciona pelo menu.
- Redefinir tudo para padrões restaura as teclas fornecidas.

Atalhos são despachados antes dos aceleradores de menu e funcionam em toda a janela, inclusive quando a janela do reprodutor tem o foco, e o caminho pelo teclado anuncia a si mesmo onde o caminho pelo menu fica silencioso. Suas alterações são armazenadas com suas configurações e sobrevivem a atualizações.

## Atalhos de teclado padrão {#shortcuts-reference}

Feeds:

- Ctrl+N: Adicionar feed.
- F5: Atualizar feeds. Shift+F5: Parar atualização. Ctrl+F5: Atualizar o feed selecionado.
- F2: Editar feed ou categoria.
- Ctrl+Shift+R: Marcar todos os itens como lidos.
- Ctrl+Shift+F: Encontrar um podcast ou feed RSS.

Artigos e visualizações:

- Ctrl+D: adicionar ou remover dos Favoritos.
- Backspace: alternar lido e não lido. Delete: excluir. Shift+Delete: excluir sem confirmar.
- Ctrl+E: focar o campo de pesquisa.
- Ctrl+Shift+H: visualização avançada de texto completo.
- Ctrl+1 a Ctrl+3: todos, não lidos, lidos. Ctrl+4 a Ctrl+6: mídia e não mídia, com mídia, sem mídia.

Reprodutor:

- Ctrl+P: reproduzir ou pausar. Ctrl+S: parar. Ctrl+Shift+P: mostrar ou ocultar o reprodutor.
- Ctrl+Left e Ctrl+Right: buscar posição. Ctrl+Up e Ctrl+Down: volume.
- Ctrl+Shift+U, Ctrl+Shift+D, Ctrl+Shift+N: acelerar, desacelerar, normal.
- Ctrl+Shift+E: equalizador.
- Ctrl+Shift+C: fila de reprodução. Ctrl+Shift+T e Ctrl+Shift+V: próximo e anterior.

Aplicativo:

- F1: este guia, aberto na seção do que você estiver usando.
- Ctrl+comma: Configurações.
- Ctrl+Shift+A: anunciar a versão em execução.
- Ctrl+X, Ctrl+C, Ctrl+V, Ctrl+A: recortar, copiar, colar, selecionar tudo.

Comandos não listados aqui são fornecidos sem associação e podem receber qualquer tecla em Ferramentas, Atalhos de teclado.

## Idioma da interface {#language}

A interface do BlindRSS é traduzida para quinze idiomas. Configurações, Geral escolhe um ou a deixa seguindo o idioma do sistema. A alteração entra em vigor quando você reinicia.

Traduções são entregues entre lançamentos do aplicativo, além de com eles, portanto uma tradução corrigida chega até você sem esperar por uma nova versão.

Este guia segue o mesmo idioma quando existe um guia traduzido para ele e volta para o inglês quando não existe.

## Ícone da bandeja e teclas de mídia {#tray}

O BlindRSS pode ficar na bandeja do sistema. Configurações, Geral decide se fechar a janela a envia para a bandeja, se minimizar faz isso e se ele inicia lá.

O ícone da bandeja tem controles de reprodução e reabre a janela principal. As teclas de mídia do teclado — reproduzir/pausar, parar, próximo, anterior — controlam o reprodutor do BlindRSS em todo o sistema.

## Adicionando atalhos da área de trabalho {#desktop-shortcuts}

Arquivo, Adicionar atalhos cria atalhos para o BlindRSS na área de trabalho, no Menu Iniciar e na barra de tarefas. Marque os que quiser e escolha OK; o resultado de cada um é informado de volta.

Uma entrada no Menu Iniciar também é o que o Windows exige antes que um aplicativo possa gerar notificações, portanto vale a pena tê-la mesmo se você iniciar o BlindRSS de outra maneira.

## Verificando atualizações {#updates}

Ajuda, Verificar atualizações pergunta se há uma versão mais nova disponível e oferece instalá-la.

Cada atualização é verificada antes de ser aplicada: seu SHA-256 deve corresponder ao manifesto publicado e, no Windows, sua assinatura Authenticode deve ser válida. Uma atualização que falhar em qualquer verificação não é instalada.

"Verificar atualizações ao iniciar" em Configurações, Geral faz isso automaticamente, e "Instalar atualizações automaticamente sem confirmação" em Configurações, Avançado as aplica sem perguntar. Suas configurações, banco de dados e downloads não são alterados por uma atualização.

## Anunciando a versão {#version}

Ajuda, Anunciar versão (Ctrl+Shift+A) fala a versão em execução do BlindRSS diretamente ao leitor de tela.

O comando do próprio leitor de tela para "informar a versão do aplicativo" lê o recurso de versão do executável, que funciona em uma compilação instalada, mas informa a versão do Python quando o BlindRSS é executado do código-fonte. Este comando dá a resposta correta de qualquer forma.

## Sobre o BlindRSS {#about}

Ajuda, Sobre mostra a versão, a licença e links: o perfil do GitHub, o repositório e o changelog.

O BlindRSS está sob a licença MIT — use-o, altere-o, redistribua-o ou empacote-o para os repositórios de uma distribuição, sem precisar de permissão.

## Usando esta janela de ajuda {#help-window}

Esta janela é um leitor simples e totalmente acessível por teclado para o guia.

- A lista de conteúdo contém todas as seções. Percorra-a com as setas; selecionar uma seção leva o texto até ela e anuncia seu título.
- A área de texto é somente leitura e selecionável, portanto um leitor de tela pode lê-la linha por linha e você pode copiar dela.
- Ctrl+F move para a caixa de pesquisa. Digite uma palavra e pressione Enter para saltar para a próxima ocorrência.
- F3 encontra a próxima ocorrência, Shift+F3 a anterior. A pesquisa volta ao início.
- Tab e Shift+Tab movem-se entre a caixa de pesquisa, a lista de conteúdo e o texto.
- Escape fecha a janela.

F1 em qualquer lugar do BlindRSS abre esta janela na seção do que você estiver usando — o controle focado, o diálogo ativo, o item de menu destacado ou o reprodutor. Quando não há seção para isso, o guia abre no início.

O guia é exibido no idioma da interface do BlindRSS quando existe uma tradução dele e em inglês caso contrário.

## Solução de problemas {#troubleshooting}

Um feed parou de atualizar. Procure o motivo em Feeds com erros. Um feed movido precisa ter seu endereço corrigido em Propriedades do feed; um site que exige verificação de navegador precisa de Importando cookies do site.

Um vídeo do YouTube não reproduz. Importe cookies do YouTube em Configurações, YouTube, e ative "Reproduzir YouTube baixando primeiro". Um erro "entre para confirmar que você não é um bot" sempre significa cookies.

A reprodução trava. Aumente o cache de rede em Configurações, Reprodutor de mídia e desligue Pular silêncio, que é experimental e consome CPU.

Um site não retorna nada. Altere a identificação do navegador em Configurações, Avançado; alguns sites rejeitam completamente clientes desconhecidos.

Nada é falado quando um comando é executado. Verifique Anúncios em Configurações, Notificações — cada evento pode ser ligado ou desligado individualmente, e há um botão de teste.

Algo se comporta de modo estranho e você quer relatar. Ative o modo de depuração em Configurações, Geral, reproduza o problema e anexe o blindrss.log gravado ao lado de suas configurações e dados.

## Suporte e comunidade {#support}

Erros e solicitações de recursos pertencem ao rastreador de problemas do GitHub, em github.com/serrebidev/BlindRSS/issues.

Para perguntas, ajuda e notícias de lançamento, o grupo SerrebiProjects no Telegram em t.me/SerrebiProjects é o lugar mais rápido para obter uma resposta.

Traduções são sempre bem-vindas. Se você fala um dos idiomas suportados e algo estiver errado, um pull request que o corrija quase certamente será aceito — consulte locale/README.md no repositório para saber como os arquivos são organizados. O mesmo vale para este guia: uma cópia traduzida pertence a docs/help/<language>.md, mantendo os marcadores {#anchor} exatamente como estão no arquivo em inglês para que a ajuda sensível ao contexto continue funcionando.
