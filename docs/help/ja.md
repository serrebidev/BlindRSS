# BlindRSS ユーザーガイド

## BlindRSS ユーザーガイド {#user-guide}

BlindRSS は、スクリーンリーダーに配慮したデスクトップ RSS・ポッドキャストクライアントです。RSS と Atom フィードを読み、ポッドキャストと動画のエンクロージャを再生し、単独でも Miniflux、Inoreader、The Old Reader、BazQux などのホスト型アカウントでも利用できます。

このガイドはアプリケーション内に保存されているため、インターネット接続や Web ブラウザーなしで使えます。BlindRSS のどこからでも F1 を押すと開きます。使用中のコントロール、ダイアログ、メニュー項目、またはウィンドウに専用の節がある場合、F1 は先頭ではなくその節でガイドを開きます。

ここにあるすべての機能にはキーボードで到達できます。目次リストで節を移動するか、検索ボックスでガイド内の語を探してください。

## はじめに {#getting-started}

BlindRSS を初めて起動したとき、フィードはありません。追加方法はいくつかあります。

- Ctrl+N を押してアドレスからフィードを追加します。フィードの追加を参照してください。
- Ctrl+Shift+F を押して、名前でポッドキャストとフィードのディレクトリを検索します。ポッドキャストと RSS フィードを探すを参照してください。
- 別のリーダーからエクスポートした OPML ファイルをインポートします。OPML のインポートを参照してください。
- YouTube Takeout アーカイブをインポートして、すでにフォローしているすべてのチャンネルを購読します。YouTube Takeout アーカイブのインポートを参照してください。
- Tools、Settings、Provider でホスト型アカウントにサインインすると、BlindRSS はそのアカウントに既にある購読を読み込みます。オンラインアカウントとプロバイダーを参照してください。

フィードを追加したら F5 を押して更新します。新しい記事は記事リストに表示され、未読数はツリーの各フィードの横に表示されます。

早めに確認しておきたい場所は、Tools、Settings（BlindRSS の動作）、Tools、Keyboard Shortcuts（すべてのコマンドとキー）、そしてこのガイドです。

## メインウィンドウ {#main-window}

メインウィンドウには、メニューバーとステータスバーに加えて 4 つの主な領域があります。Tab と Shift+Tab で領域間を移動し、多くのウィンドウマネージャーでは F6 でペインを切り替えます。

- 左側のフィードとフォルダーのツリー。
- 記事リストの上にある検索フィールド。
- 記事リスト。
- 記事リストの下にある閲覧ペイン。

メニューバーには File、Edit、View、Player、Tools、Help があります。Alt を押してから矢印キーを使います。すべてのメニュー項目には各インターフェイス言語でアクセスキーがあり、メニューバーは両端で折り返します。

サイズ、選択したフィード、ウィンドウ状態は起動の間で記憶されます。Settings、General の "Remember last selected feed/folder on startup" で、最後に読んでいたフィードを BlindRSS が再び開くかを制御します。

## フィードとフォルダーのリスト {#feed-tree}

左のツリーには、フィード、それらをまとめるカテゴリー、Smart Folders、保存済み検索、組み込みビュー（All Feeds、Favorites、Deleted Articles、Feeds with Errors）が表示されます。

- 上下矢印で項目間を移動します。
- Right Arrow でカテゴリーを展開し、Left Arrow で折りたたみます。
- Enter または項目の選択で、その記事を記事リストに読み込みます。
- F2 で選択したフィードまたはカテゴリーのプロパティを開きます。
- Applications キーまたは Shift+F10 でコンテキストメニューを開きます。

各フィードには未読数が表示されます。展開・折りたたみ状態のカテゴリーは記憶されるため、次回起動時もツリーは同じように見えます。

更新に失敗したフィードも通常どおり一覧に表示されます。Feeds with Errors ビューでまとめて確認できるので、密かに停止したフィードを見逃しません。

## 記事リスト {#article-list}

記事リストには、現在の Article Filter、並べ替え順、検索語を適用したうえで、ツリーで選択されているものの記事が表示されます。

- 上下矢印で記事を移動します。閲覧ペインも追従します。
- Enter で選択した記事を開きます。
- Shift+Up と Shift+Down で選択範囲を広げ、複数の記事に一括操作を実行できます。
- Backspace で選択した記事の既読・未読を切り替えます。
- Delete で選択した記事を削除します。Shift+Delete では確認を表示せずに削除します。
- Ctrl+D でお気に入りに追加または削除します。
- Applications キーまたは Shift+F10 でコンテキストメニューを開きます。

表示する列とその順序は、全体およびフィードごとに設定できます。記事リストの列を参照してください。

## 閲覧ペイン {#reading-pane}

記事リストの下の閲覧ペインには、選択した記事のテキストが表示されます。読み取り専用のテキスト領域なので、スクリーンリーダーで行、単語、文字ごとに読め、テキストを選択してコピーできます。

- Ctrl+F で記事テキスト内を検索します。
- F3 と Shift+F3 で次および前の一致へ移動します。
- テキスト内のリンクで Enter を押すと、そのリンクを開きます。

テキストの提示方法は Settings、Feeds and Articles で設定できます。見出しを通知する、リスト項目を箇条書きと番号で示す、引用を示す、リンクにアドレスを表示する、表を説明する、画像の代替テキストを含める、といった設定があります。画像の代替テキストは、フィードのコンテキストメニューから一つのフィードだけで強制的にオンまたはオフにもできます。

フィードが短い要約だけを公開する場合、BlindRSS は記事全文を取得できます。記事全文の復元を参照してください。

## 記事ウィンドウ {#article-window}

記事を開くと、閲覧ペインではなく独立したウィンドウに表示できます。これにより記事が画面全体を使い、リストを先へ移動しても開いたままです。

このウィンドウは閲覧ペインと同じ読み取り、選択、テキスト内検索の動作をする読み取り専用テキスト領域です。Escape で閉じます。

## 検索フィールド {#search-field}

記事リスト上部の検索フィールドでは、入力して Enter で確定すると現在のビューを絞り込みます。

- Ctrl+E で検索フィールドにフォーカスを移します。
- Enter で語を適用します。
- Escape またはクリアボタンで内容を空にし、完全なリストに戻します。

検索を使わない場合、検索フィールドは非表示にできます。View メニューには Show/Hide Search Field コマンドがあります。タイトルだけを検索対象にするか、タイトルと記事テキストを対象にするかは、Settings、Feeds and Articles の "Search Matches" で設定します。

保持したい検索は、ツリーに残る保存済み検索にできます。永続検索を参照してください。

## ステータスバー {#status-bar}

メインウィンドウ下部のステータスバーには 3 つのフィールドがあります。

- フィルターに一致した記事数などの一時的なメッセージ。
- フィード更新やダウンロードの進行状況などのバックグラウンド活動。
- 再生状態: 再生中のものと、経過時間および残り時間。

これらは意図的に分離されています。読んでいる途中に、更新メッセージが検索結果数を上書きすることはありません。

## コンテキストメニュー {#context-menus}

フィードツリーと記事リストにはそれぞれ、Applications キーまたは Shift+F10 で開くコンテキストメニューがあります。選択中のものに適用するコマンド（更新、既読化、編集、削除、リンクのコピー、メディアのキュー追加など）が含まれます。

コンテキストメニューでも F1 を使えます。項目を強調表示して F1 を押すと、それを説明するこのガイドの節を開きます。

## フィードの追加 {#adding-feeds}

File、Add Feed（Ctrl+N）で、アドレスからフィードを購読します。

フィードのアドレス、またはサイト自体のアドレスを貼り付けるか入力します。アドレスがフィードでない場合、BlindRSS はそのページでフィードを探します。YouTube チャンネルまたはプレイリストのアドレス、Mastodon または Bluesky のプロフィール、PieFed または Lemmy のコミュニティ、SoundCloud または Mixcloud のページ、Reddit または Groups.io のアドレスを貼り付けても、BlindRSS はフィードに変換できます。

フィードの配置先カテゴリーを選ぶか、カテゴリーなしのままにします。"Open in HTML view" オプションを選ぶと、このフィードの記事は既定でリッチビューで開きます。

アドレスが分からない場合は、代わりにポッドキャストと RSS フィードを探すを使用してください。

## ページ上のフィードを検出 {#detect-feeds}

File、Detect Feeds on Page は通常の Web ページのアドレスを受け取り、そのページが告知しているフィードを一覧表示します。自分でフィードリンクを探し回らずに購読できます。

これは、サイトに "subscribe" または "RSS" のリンクがあっても簡単に到達できない場合や、ページに複数のフィード（すべての投稿、あるカテゴリー、コメント）があり選びたい場合に適したコマンドです。

## ポッドキャストと RSS フィードを探す {#find-podcast}

Tools、Find a Podcast or RSS Feed（Ctrl+Shift+F）は、名前、話題、サイトアドレスでポッドキャストとフィードのディレクトリを検索するため、フィードアドレスを知らなくても購読できます。

1. 検索ボックスに探しているもの（ポッドキャスト名、話題、またはサイトアドレス）を入力します。
2. ソースを選ぶか、"All sources" のままにします。
3. Enter または Search ボタンを押します。
4. 結果リストを矢印キーで移動します。各行にはタイトル、取得元のディレクトリ、詳細が表示されます。
5. 結果で Enter を押すか、OK を選んで購読します。

検索は複数のディレクトリに同時に実行され、応答したものから結果が届きます。そのため、読んでいる間にもリストは増えます。Escape でダイアログを閉じ、検索を停止します。

## ポッドキャストとフィードのディレクトリ {#podcast-directories}

Find a Podcast or RSS Feed の Source ボックスで検索場所を選びます。"All sources"、"All podcast sources"、"All RSS feed sources" のほか、次のディレクトリを個別に利用できます。

- ポッドキャストディレクトリ: iTunes（Apple Podcasts）、gPodder、fyyd、Podverse、SoundCloud、Mixcloud。
- フィードディレクトリ: NewsBlur、Feedspot、Google News、Bing News、Feedly。
- サイトとコミュニティの検索: YouTube、Reddit、Groups.io、Fediverse（Mastodon、Bluesky、PieFed、Lemmy または Kbin）。それぞれ単独でも選択できます。
- アドレスベースの検出: Feedsearch と BlindRSS 独自の Web サイトスキャン。サイトを取得して内部のフィードを探します。

単一のディレクトリだけには依存しません。"All sources" の検索ではポッドキャストと RSS のグループを一緒に照会して結果を統合し、広い Google News クエリフィードは直接のフィード一致より下に保ちます。

## 検索結果を購読する {#subscribing}

Find a Podcast or RSS Feed、Video Search、Podcast Archive の検索ボタンなど、どの検索ダイアログでも、結果で Enter を押すか、選択した状態で OK を選ぶと購読します。

BlindRSS はまず結果を実際のフィードアドレスへ解決します。そのため、ディレクトリで見つけたポッドキャスト、YouTube チャンネル、Fediverse アカウントはいずれも同じ方法で購読できます。新しいフィードはツリーに現れ、直ちに更新されます。

特定のカテゴリーに置きたい場合は、後からコンテキストメニューまたは Feed Properties で移動してください。

## ポッドキャストアーカイブ {#podcast-archive}

Tools、Podcast Archive では、フィードに残るエピソードと BlindRSS が復元した古いエピソードの両方を含む、ポッドキャストの完全なエピソード履歴を参照し、一括でダウンロードできます。

多くのポッドキャストフィードは最新エピソードだけを公開します。アーカイブの復元はバックグラウンドで自動実行されます。このウィンドウでは状態の確認、手動再試行、見つかったもののダウンロードができます。

- Podcast ボックスでポッドキャストを選びます。
- Filter episodes は入力に応じてリストを絞り込みます。
- Rescan archive はそのポッドキャストの復元をもう一度実行します。
- Find or add podcast はフィード検索を開くため、まだ購読していないポッドキャストもアーカイブできます。
- Play は選択したエピソードを再生し、Download selected はそれをダウンロードし、Download all は表示中のリスト全体をダウンロードします。
- Cancel downloads は実行中の一括ダウンロードを停止します。

一括ダウンロード中もウィンドウは開いたままなので、読み続けられます。

## 動画検索 {#video-search}

Tools、Video Search は、yt-dlp が照会できるすべてのサイトを一度に検索し、見つかった動画の再生、キュー追加、購読を可能にします。

- 検索語を入力し、Enter または Search ボタンを押します。
- scope ボックスで検索対象を一つのサイトに限定できます。既定ではすべてを検索します。
- 各サイトの応答に応じて、主流サイトを先に結果が届きます。プレースホルダーとして届いたタイトルは、解決されると埋められます。
- Load More Results は各サイトから次の一群を取得します。
- 列見出しで並べ替えると、到着済みの結果を並べ替えます。

複数のサイトで見つかった同一動画は 1 行に統合されます。Settings、Advanced の "Enable adult sites in Video Search" をオンにしない限り、成人向けサイトは除外されます。

## URL で記事を開く {#open-article-url}

File、Open Article は任意の Web ページのアドレスを受け取り、抽出テキストを閲覧ペインに表示して、ほかの記事と同じ閲覧オプションで、BlindRSS 内で記事のように読みます。

何も購読せず、送られてきた一回限りのページを読むために使います。ページがフォーラムまたはディスカッションスレッドであれば、BlindRSS はスレッド全体を読みます。フォーラムとディスカッションスレッドを参照してください。

## メディア URL を開く {#open-media-url}

File、Open Media URL は、何も購読せずに、アドレスからの音声または動画を組み込みプレーヤーで再生します。

直接のメディアリンクと、yt-dlp が解決できるページアドレス（YouTube、Rumble、Odysee、SoundCloud など多数）を受け入れます。結果はほかの項目と同じように再生され、再生キューに追加できます。

## フィードの削除 {#removing-feeds}

File、Remove Feed は選択したフィードを購読解除します。同じコマンドはフィードのコンテキストメニューにもあります。

フィードを削除すると、データベースからその記事も削除されます。すでにディスクへダウンロードしたものには触れません。ホスト型プロバイダーを使う場合は、そのアカウントにも購読解除が送信されます。

カテゴリー全体とその中のすべてを削除するには、カテゴリーのコンテキストメニューで Delete Category and Feeds を使用します。カテゴリーとサブカテゴリーを参照してください。

## フィードのプロパティ {#feed-properties}

F2、またはコンテキストメニューの Edit Feed で、選択したフィードのプロパティを開きます。

- 上書きできるタイトル。コンテキストメニューの "Reset Title to Feed Default" でフィード本来のタイトルに戻します。
- アドレスと所属するカテゴリー。
- 新規記事で通知を出すかどうか。
- リッチ HTML ビューで開くかどうか。
- List Headers タブにある、グローバル設定を上書きする独自の記事リスト列レイアウト。

記事リストのコンテキストメニューにある View Feed Description は、フィード自身が公開する説明を表示します。

## カテゴリーとサブカテゴリー {#categories}

カテゴリーはツリー内でフィードをまとめ、入れ子にできます。カテゴリーにはフィードとさらに下位のサブカテゴリーの両方を含められます。

- File、Add Category で作成します。
- カテゴリーのコンテキストメニューの Add Subcategory で、その中に作成します。
- Edit Category で名前変更または移動します。カテゴリーのプロパティを参照してください。
- Remove Category はカテゴリーを削除しますが、フィードは保持します。
- Delete Category and Feeds はカテゴリーを削除し、その中のすべてを購読解除します。
- Import OPML Here はファイルをそのカテゴリーに直接インポートします。
- Export Category to OPML はその枝だけをエクスポートします。

一部のホスト型プロバイダーはカテゴリーを単一のフラットなリストに保持します。その場合 BlindRSS はその旨を知らせ、"move to parent" オプションは利用できません。

## カテゴリーのプロパティ {#category-properties}

Edit Category は、カテゴリーの名前と、配置先の親カテゴリーを開きます。

カテゴリーの名前を変更してもすべてのフィードは保持されます。移動すると、サブカテゴリーを含む枝全体が移動します。

## フィードの更新 {#refreshing}

- F5 ですべてのフィードを更新します。
- Ctrl+F5 で選択したフィードまたはカテゴリーだけを更新します。
- Shift+F5 で実行中の更新を停止します。
- カテゴリーのコンテキストメニューの Refresh Category で、その枝を更新します。

Refresh Feeds と Stop Refresh は同時には一方だけが利用可能なので、キーボードコマンドはメニューが提供するものと一致します。進行状況はステータスバーの 2 番目のフィールドに表示されます。

自動更新は Settings、Feeds and Articles で設定します。間隔、同時に更新するフィード数、ホストごとの接続数、フィードごとのタイムアウト、失敗したフィードの再試行回数を設定できます。"Automatically refresh feeds upon start" は起動時にすべてを更新し、起動時の負荷オプションでキャッシュを使うか完全更新を強制するかを選びます。

## エラーのあるフィード {#feed-errors}

Feeds with Errors ビューと File、View Feed Errors には、最後の更新に失敗したフィードと理由が表示されます。

静かに動作を停止したフィードは、新しい記事がないフィードとまったく同じに見えます。そのためこのビューがあります。ここから次のことができます。

- Refresh Selected で今すぐ再試行します。
- Copy Details でエラーテキストをクリップボードへ入れます。
- Feed Properties でアドレスを修正します。
- フィードが完全になくなった場合は Remove Feed を使います。

よくある原因は、移転または終了したフィード、ブラウザー確認が必要になったサイト（サイト Cookie のインポートを参照）、一時的なサーバー障害です。

## OPML のインポート {#import-opml}

OPML はフィード購読リストの標準ファイル形式です。どのフィードリーダーもこれをエクスポートできるため、OPML を使えば別のリーダーから BlindRSS へ、一つずつ追加せずに購読を移せます。

File、Import OPML はファイルを尋ね、その中のすべてのフィードを、ファイルが記述するカテゴリー構造を保って追加します。すでに購読しているフィードは重複しません。

カテゴリーのコンテキストメニューにある Import OPML Here は、最上位ではなくそのカテゴリー内にインポート全体を配置します。

別のリーダーから OPML ファイルを取得するには、その設定内で "Export"、"Backup"、または "Subscriptions" を探してください。

## OPML のエクスポート {#export-opml}

File、Export OPML は、カテゴリーを含むすべての購読を OPML ファイルへ書き出します。

購読のバックアップ、別のリーダーまたはマシンへの移行、他者とのフィードセット共有に使えます。カテゴリーのコンテキストメニューの Export Category to OPML はその枝だけをエクスポートします。

## YouTube Takeout アーカイブのインポート {#import-youtube-takeout}

Google Takeout は Google のデータエクスポートサービスです。YouTube Takeout アーカイブは、購読チャンネルの一覧を含む YouTube データの ZIP ファイルです。File、Import YouTube Takeout はこの ZIP を読み、チャンネルをフィードとして購読するため、各チャンネルの新しい動画が記事として届きます。

アーカイブを取得するには、次の手順を実行します。

1. takeout.google.com に移動し、YouTube の購読がある Google アカウントでサインインします。
2. "Deselect all" を選び、YouTube と YouTube Music だけを選択します。
3. "All YouTube data included" では少なくとも "subscriptions" を残します。"history" と "playlists" は任意ですが、BlindRSS でも利用できます。
4. ZIP ファイルとして一度エクスポートし、Google のメールを待ちます。大きなアーカイブでは数時間かかることがあります。
5. ZIP をダウンロードし、このコマンドで指定します。

BlindRSS は見つけたものをソース別にグループ化して表示し、どのグループをインポートするか選べます。

- Subscriptions: フォローしているチャンネル。
- History: 視聴したがフォローしていないチャンネル。
- 自分のチャンネル。
- Playlists: それぞれ独自のフィードとして扱われます。

重複アドレスは取り除かれるため、後から 2 つ目のアーカイブをインポートしても新しいものだけが追加されます。ZIP がディスクへ展開されることはなく、内部の小さなデータファイルだけが読み込まれます。

## 永続検索 {#persistent-search}

永続検索は、ツリー内に独自の項目として残る検索語です。一致する記事は常に矢印キー一つで到達できます。

Tools、Configure Persistent Search でリストを管理します。Add は語から作成し、Remove は削除します。保存済み検索はツリーに現れ、選択するたびに再評価されるため、常に現在の記事を反映します。

すべてのフィードを横断して追う話題（人物名、製品、場所）に使います。語句より構造化した条件が必要な場合は Smart Folders を使ってください。

## スマートフォルダー {#smart-folders}

Smart Folder は、記事の取得元フィードではなくルールで内容が定義されるツリー内のフォルダーです。

ツリーのコンテキストメニューの New Smart Folder はルールエディターを開きます。ルールは "match all"（and）または "match any"（or）で結んだ条件の集合で、条件グループも入れ子にできるため、"(A and B) or C" を表現できます。

条件は次のフィールドをテストします。

- はい・いいえのフィールド: read、favorite、opened、updated。
- テキストフィールド: title、content、description、author、feed、url、tag（サイト自身が公開するカテゴリーまたはタグ）。

テキスト条件は、含む、含まない、等しい、またはで始まる、を使います。

Smart Folders は何かを移動またはコピーすることはありません。すでに持っている記事に対するビューです。到着時に記事を変更するには Filter Rules を使います。

## フィルタールール {#filter-rules}

Tools、Filter Rules は BlindRSS の記事仕分けエンジンです。メールフィルターが受信メールに対して動作するように、ルールは受信記事に対して実行されます。

各ルールは、Smart Folders と同じルールエディターを使う条件と、一連のアクションを組み合わせます。

- 記事をカテゴリーへ移動する。
- 記事をその場に残しつつ、カテゴリーでラベル付けする。
- 既読にする。
- お気に入りにする。
- 設定済みの削除動作に従って削除する。
- 新規記事通知をスキップする。

ルールはリスト順に実行され、一致する有効なルールはすべてアクションを追加します。停止するよう設定したルールは、一致後にその記事のパイプラインを終えるため、後のルールは処理しません。どれを優先するかはルールを上下へ移動して制御します。

アクションのないルールは何もせず拒否されます。そのため、未完成のルールが気付かないうちに記事を飲み込むことはありません。

## 記事フィルター {#article-filter}

View、Article Filter は、既読状態とメディア添付の有無であらゆるビューを制限します。二つのグループは組み合わさります。

- Ctrl+1: すべての記事。
- Ctrl+2: 未読のみ。
- Ctrl+3: 既読のみ。
- Ctrl+4: メディアあり・なし。
- Ctrl+5: メディアありのみ。
- Ctrl+6: メディアなしのみ。

このフィルターは Smart Folders と保存済み検索を含むツリーの選択対象すべてに適用され、起動の間で保持されます。"With media only" は、混在するフィードをポッドキャストリストに変える最も速い方法です。

## 記事の並べ替え {#sorting}

View、Sort By は、記事リストを日付、名前、著者、説明、フィード、または状態で並べます。Ascending は方向を切り替えます。既定は新しいものが先です。

並べ替えはすべてのビューに適用され、起動の間で記憶されます。フィードでの並べ替えは、記事が多数のソースから一度に来る All Feeds と Smart Folders で便利です。

## 記事リストの列 {#list-headers}

記事リストの列、順序、幅は自由に選べます。Settings、List Headers でグローバルなレイアウトを設定します。フィード独自の List Headers タブはそのフィードだけで上書きし、"Use the global column layout" で上書きをオフに戻します。

列が少ないほどスクリーンリーダーが各行で読む量も少なくなるため、使わない列を取り除く価値があります。

## 記事を開く {#opening-articles}

リスト内の記事で Enter を押すと開きます。記事と設定に応じて、閲覧ペイン、独立したウィンドウ、またはリッチ HTML ビューで開きます。

- コンテキストメニューの Open Article も同じ動作をします。
- Open in Browser は記事のアドレスをシステムの Web ブラウザーへ渡します。
- Open Accessible Browser は代わりに BlindRSS 内でページを読みます。Accessible Browser を参照してください。

動作を変更していない限り、記事を開くと既読になります。

## 既読と未読の記事 {#read-status}

- Backspace または Toggle Read/Unread で選択した記事を切り替えます。
- Ctrl+Shift+R で現在のビューのすべてを既読にします。
- フィードまたはカテゴリーのコンテキストメニューの Mark All Items as Read も、その枝に対して同じ操作をします。
- 記事リストのコンテキストメニューの Mark as Read と Mark as Unread は選択全体に作用し、影響する記事数を示します。

未読数はツリーの各フィードの横に表示されます。Article Filter では既読記事を完全に隠せます。

## お気に入り {#favorites}

Ctrl+D で選択した記事を Favorites に追加します。すでにある場合は削除します。ツリーの Favorites ビューにはマークしたすべてが表示されます。

お気に入りは保持ポリシーを超えて残ります。スターを付けた記事は古い記事の整理時にも削除されません。favorite は Smart Folders と Filter Rules の条件にも使えます。

## 削除済み記事 {#deleted-articles}

Delete の動作は Settings、General の "When I delete an article" で設定できます。

- Deleted Articles へ移動する。そこから復元できます。
- 完全に削除する。
- 指定したカテゴリーへ移動する。

最初の設定では、ツリーの Deleted Articles ビューに削除したものが表示されます。Restore で記事を戻せ、このビュー内から削除すると完全に削除されます。

"Confirm before deleting articles" は確認プロンプトを制御します。Shift+Delete は常にこれをスキップします。

## 記事全文の復元 {#full-text}

多くのフィードは見出しと一、二文だけを公開します。BlindRSS は記事ページを取得して実際のテキストを抽出できるため、閲覧ペインには抜粋ではなく記事全体が表示されます。

これはリストを移動する際にバックグラウンドで自動的に起こり、結果はキャッシュされます。Settings、Feeds and Articles の "Cache full text in background" は現在位置の周辺記事を先取りするため、リストを下へ移動してもネットワーク待ちになりません。

サイトをまったく読めない場合、通常はブラウザー確認の背後にあります。サイト Cookie のインポートを参照してください。

## リッチな記事全文ビュー {#rich-view}

Ctrl+Shift+H は閲覧ペインをリッチ HTML ビューへ切り替えます。見出し、リスト、表、リンクを、スクリーンリーダー自身の構造ナビゲーションコマンドで移動できる実際の要素として、ブラウザーのようにレンダリングします。

プレーンテキストビューは高速で予想外の動作をしないため既定です。記事の構造自体に意味がある場合、リッチビューを使う価値があります。

Feed Properties でフィードを常にリッチビューで開くよう設定でき、リッチビューのリンクはビュー内ではなくシステムブラウザーで開きます。

## アクセシブルブラウザー {#accessible-browser}

View、Open Accessible Browser は、システムブラウザーへ渡す代わりに、スクリーンリーダーで読むために作られたウィンドウでページを BlindRSS 内に開きます。

これは操作ではなく読む必要があるページ、またはサイト自身のインターフェイスを移動しにくい場合に適したツールです。BlindRSS の Cookie とブラウザー識別設定を共有するため、Cookie をインポート済みならブラウザー確認の背後のページもここで開きます。

## YouTube 動画 {#youtube}

YouTube のチャンネルまたはプレイリストのアドレスは、ほかのフィードと同じように購読できます。その動画は記事として届き、説明、文字起こし、チャプターリストが本文内に表示されるため、動画を視聴する代わりに読めます。

再生には yt-dlp を使います。Settings、YouTube で以下を制御します。

- Cookie ファイル。アクセス権のある年齢制限・メンバー限定動画を BlindRSS が見られるようにします。ブラウザーから直接インポートするか、Downloads フォルダーの cookies.txt エクスポートから自動取得できます。
- "Play YouTube by downloading first"。開始は遅くなりますが、はるかに信頼性が高くなります。
- 再生キャッシュフォルダーとその最大サイズ、および消去ボタン。

Import YouTube Takeout は、すでにフォローしている全チャンネルを一度に購読します。

## フォーラムとディスカッションスレッド {#forums}

Reddit、Lemmy、Groups.io、Google Groups は、一度に一投稿ずつではなくスレッド全体として読まれます。ディスカッションを開くと、元の投稿と返信が一続きのテキストで得られるため、ブラウザーでスレッドをたどるよりずっと速く読めます。

購読もほかのフィードと同じです。subreddit、コミュニティ、またはグループのアドレスを貼り付けます。GitHub リポジトリも同じように対応しており、Mastodon、Bluesky、PieFed のアカウントとコミュニティも対応しています。

## 切り取り、コピー、貼り付け {#clipboard}

Edit メニューには標準クリップボードコマンド、Cut（Ctrl+X）、Copy（Ctrl+C）、Paste（Ctrl+V）、Select All（Ctrl+A）があり、すべてのテキストフィールドと閲覧ペインで使えます。

BlindRSS には、認識しているものをコピーするコマンドもあります。

- Copy Link: 記事のアドレス。
- Copy Media Link: 音声または動画のアドレス。
- Copy Text: 閲覧ペインで読む記事テキスト。
- Copy Feed URL: 選択したフィードのアドレス。
- Copy Image Link: 画像を含む記事で使います。

## 組み込みプレーヤー {#player}

BlindRSS は VLC を介してポッドキャストと動画のエンクロージャを自ら再生するため、再生中もアプリケーションから離れません。Ctrl+Shift+P でプレーヤーウィンドウを表示または非表示にでき、どちらでも再生は続きます。

再生はローカルの range-cache proxy によって滑らかになるため、低速な接続でも長いエピソードを素早くシークできます。YouTube、Rumble、Odysee など解決が必要なストリームは、最初に yt-dlp を通ります。

Settings、Media Player の "Show player window when starting playback" で、再生開始時にウィンドウを自動表示するかを決めます。

## プレーヤー操作 {#player-controls}

プレーヤーウィンドウには、タブ順で、再生状態、位置スライダー、経過・合計時間、巻き戻し・早送りボタン、速度ボックス、チャプターボタン、音量スライダーがあります。すべてキーボードで到達・操作でき、現在値を通知します。

- Ctrl+P で再生と一時停止を切り替えます。
- Ctrl+S で停止します。
- Ctrl+Left と Ctrl+Right で巻き戻し・早送りをし、押し続けると繰り返します。macOS では Ctrl+Left と Ctrl+Right は Mission Control に属するため、Option+Left と Option+Right を使います。
- Ctrl+Up と Ctrl+Down で音量を変更します。

何かを再生している間、シークキーと音量キーはダイアログ内を含め BlindRSS のどこからでも動作します。そのため一時停止するためにプレーヤーウィンドウを探す必要はありません。

## プレーヤーのキーボードショートカット {#player-shortcuts}

- Ctrl+Shift+P: プレーヤーウィンドウの表示または非表示。
- Ctrl+P: 再生または一時停止。
- Ctrl+S: 停止。
- Ctrl+Left と Ctrl+Right: 巻き戻しと早送り（macOS では Option+Left と Option+Right）。
- Ctrl+Up と Ctrl+Down: 音量を上げる・下げる。
- Ctrl+Shift+U、Ctrl+Shift+D、Ctrl+Shift+N: 速く、遅く、通常速度に戻す。
- Ctrl+Shift+E: イコライザー。
- Ctrl+Shift+C: 再生キュー。
- Ctrl+Shift+T と Ctrl+Shift+V: キュー内の次と前。

これらはすべて Tools、Keyboard Shortcuts で再割り当てできます。速度コマンドは意図的に Ctrl+Shift+digit や Ctrl+Shift+period ではなく文字を既定にしています。Windows と一部の NVDA アドオンが、アプリケーションに届く前にそれらを取得するためです。

## 再生速度 {#playback-speed}

Player、Playback Speed は、音程を保ったまま、メディアの再生速度を半速から 3 倍速まで変更します。

- Ctrl+Shift+U で速くし、Ctrl+Shift+D で遅くし、Ctrl+Shift+N で 1x に戻します。
- サブメニューの固定段階は 0.5x、0.75x、1x、1.25x、1.5x、1.75x、2x、2.5x、3x です。
- プレーヤーウィンドウには直接設定できる速度ボックスがあります。

Settings、Media Player の "Default Playback Speed" で、すべての再生開始時の速度を設定します。

## イコライザー {#equalizer}

Ctrl+Shift+E、または Player、Equalizer で、プリアンプ付き 10 バンドイコライザーを開きます。

- "Enable equalizer" は全体をオン・オフします。
- 各バンドは、変更時にゲインを通知するスライダーです。
- Save as Preset は現在のバンドを名前付きで保存し、Delete Preset は一つを削除します。
- Reset (Flat) はすべてのバンドをゼロへ戻します。

イコライザーは BlindRSS が再生するすべてに適用され、その設定は記憶されます。

## チャプター {#chapters}

ポッドキャストと YouTube 動画にはチャプターが含まれることがよくあります。再生中の項目にある場合、Player、Chapters に一覧が表示され、選択したチャプターへシークできます。

- チャプターのサブメニューは項目のチャプターが判明すると埋まり、ない場合は "No chapters available" と表示します。
- プレーヤーウィンドウにはチャプターボタンとチャプターボックスがあります。
- 記事リストのコンテキストメニューの Chapter Links には、チャプター説明にあるリンクが表示されます。

リスト内を移動する間にチャプターはバックグラウンドで読み込まれるため、通常は再生を押す前に準備できています。

## 再生キュー {#play-queue}

再生キューは次に再生するもののリストです。

- Ctrl+Shift+C でキューウィンドウを開きます。
- Ctrl+Shift+T と Ctrl+Shift+V で次と前の項目を再生します。
- 記事リストのコンテキストメニューの Add to Play Queue と Remove from Play Queue で変更します。

キューウィンドウでは、Play は選択した項目を開始し、Move Up と Move Down はキューを並べ替え、Remove は一項目を外し、Clear All は空にします。キューは再起動後も残ります。

## 他のデバイスへのキャスト {#casting}

BlindRSS は再生しているものを、ネットワーク上の Chromecast、DLNA/UPnP レンダラー、AirPlay レシーバーへ送れます。

キャストダイアログからデバイスを選びます。BlindRSS は独自のローカルプロキシを通じてストリーミングするため、元のアドレスを自力で取得できないデバイスでも項目を再生できます。キャスト中も BlindRSS からトランスポート操作を続けられます。

## 無音をスキップ {#silence-skipping}

Settings、Media Player の "Skip Silence (Experimental)" は、再生中の無音部分を検出して飛ばします。長い間のあるトークポッドキャストを目に見えて短くできます。

再生中に音声を解析するため CPU を多少使い、実験的と表示されています。再生が滑らかでない場合はオフにしてください。

## メディアのダウンロード {#downloads}

- Download は選択した記事の音声または動画を既定の形式で保存します。
- Download As では最初に形式を選べます。

ダウンロードは Settings の "Enable Downloads" でオンにする必要があります。ダウンロードフォルダー、保持ポリシー、既定の動画ダウンロード形式は同じページで設定します。既定のフォルダーはシステムの Downloads フォルダーです。

進行状況はステータスバーの 2 番目のフィールドに表示され、ダウンロード済み項目は以後ネットワークではなくディスクから再生されます。Podcast Archive はポッドキャストの全バックカタログを一括ダウンロードできます。

## 設定 {#settings}

Tools、Settings（Ctrl+comma）には、General、Feeds and Articles、YouTube、Media Player、Provider、Notifications、Translate、List Headers、Advanced、CAPTCHA Solving のタブで、すべてのオプションがあります。

Ctrl+Tab と Ctrl+Shift+Tab でタブ間を移動し、Tab で現在のタブのコントロールを移動します。OK はすべてを適用し、Cancel はすべてを破棄します。タブ位置は筋肉記憶になるため、リリース間で安定して保たれます。

タブ上で F1 を押すと、このガイドの該当タブの節を開きます。

## Settings: General {#settings-general}

- インターフェイス言語と、BlindRSS がシステム言語に従うか。変更は再起動時に有効になります。インターフェイス言語を参照してください。
- "Remember last selected feed/folder on startup"。
- "Confirm before deleting articles" と、削除時の動作（Deleted Articles へ移動、完全削除、指定カテゴリーへの移動）。
- "Debug mode (show console on startup)"。データの横にローテーションする blindrss.log も書き込みます。
- 起動とトレイ: トレイへ閉じる、トレイへ最小化する、トレイで開始する、常に最大化して開始する、起動時に更新を確認する。

## Settings: Feeds and Articles {#settings-feeds}

- 5 分から 4 時間までの自動更新間隔。
- 検索がタイトルのみ、またはタイトルと記事テキストに一致するか。
- 最大同時更新数、ホストごとの最大接続数、フィードのタイムアウト、失敗フィードの再試行回数。
- 最大キャッシュビュー数と "Cache full text in background"。
- "Automatically refresh feeds upon start" と、起動時更新の負荷（キャッシュを使う、起動時に完全更新する、常に完全更新する）。
- 記事を保持する期間を決める記事保持。Favorites は保持によって削除されません。
- 記事テキストの提示方法: 見出しの通知、箇条書きと番号によるリスト項目の表示、引用の表示、アドレス付きリンクの表示、表の説明、画像代替テキストの包含。

## Settings: YouTube {#settings-youtube}

- yt-dlp の Cookie ファイル。Browse ボタン、"Import from browser" ボタン、Downloads フォルダーの cookies.txt エクスポートを自動取得するオプションがあります。
- インストール済みブラウザーから直接 Cookie を読むこと。
- "Play YouTube by downloading first"。開始は遅くなりますが最も信頼できる選択肢です。
- YouTube 再生キャッシュフォルダー、その最大サイズ（メガバイト）、今すぐ消去するボタン。

Cookie は年齢制限・メンバー限定動画を再生可能にするものであり、"sign in to confirm you're not a bot" エラーが求めているものでもあります。

## Settings: Media Player {#settings-media-player}

- 優先するサウンドカード、またはシステム既定。
- "Skip Silence (Experimental)"。無音をスキップを参照してください。
- 既定の再生速度。
- "Show player window when starting playback"。
- ミリ秒単位のネットワークキャッシュサイズ。開始遅延と低速接続への耐性を交換します。
- ffmpeg、ffprobe、yt-dlp のパス。空欄なら自動検出し、設定したパスは検出を上書きします。検出結果は各項目の横に表示されます。
- ダウンロード: ダウンロードを有効にするか、ダウンロードフォルダー、保持ポリシー、既定の動画ダウンロード形式。
- サウンド: BlindRSS が通知音を再生するか。

## Settings: Provider {#settings-provider}

購読の保存場所を選びます。BlindRSS 内のローカル、またはホスト型アカウントです。それぞれに必要なものはオンラインアカウントとプロバイダーを参照してください。

このページには、有効なプロバイダーとその資格情報（Miniflux のアドレスと API キー、Authorize ボタン付き Inoreader の app ID と key、The Old Reader または BazQux のメールアドレスとパスワード）が表示されます。Clear Authorization は Inoreader アカウントからサインアウトします。

ローカルプロバイダーは、Add Feed と Import OPML でアプリ内に追加したフィードを使います。

## Settings: Notifications {#settings-notifications}

- "Enable notifications for new articles" と、通知テキストにフィード名を表示するか。
- 更新ごとの最大通知数と、その上限に達した際に要約通知を表示するか。
- Test Notification は今すぐ一つ送ります。
- Exclude Feeds は決して通知しないフィードを選びます。
- Announcements: BlindRSS がイベントごとにスクリーンリーダーへ直接読み上げるイベント。Test Announcement ボタンは音声と点字の両方を通じてテストを送ります。

## Settings: Translate {#settings-translate}

記事内容の自動翻訳をオンにし、それを行うサービスを選びます。

- "Enable automatic translation for article content"。
- プロバイダー: Grok (xAI)、Groq、OpenAI、OpenRouter、Gemini、Qwen。
- リストから選ぶか、en、es、fr、pt-BR などのコードとして入力する対象言語。
- 選択したプロバイダーの API キーと、任意の特定モデル。OpenRouter では "Load OpenRouter Models" が利用可能なモデル一覧を取得します。

Grok と Groq は名前が紛らわしい別サービスです。Grok は xAI のもので、console.x.ai の "xai-" で始まるキーを使います。Groq は LLaMA と Mistral をホストし、console.groq.com の "gsk_" で始まる無料キーを使います。

これは記事テキストを翻訳します。BlindRSS 自体のインターフェイス言語を変えるには、インターフェイス言語を参照してください。

## Settings: List Headers {#settings-list-headers}

グローバルな記事リスト列レイアウト（表示する列、順序、幅）を設定します。記事リストの列を参照してください。

個々のフィードは独自の Feed Properties からこれを上書きできます。

## Settings: Advanced {#settings-advanced}

- データ保存場所: データベースと設定をユーザーデータフォルダーまたはアプリケーションフォルダーに置き、両方のパスを表示します。アプリフォルダーの選択肢がポータブルインストールをポータブルにします。
- 更新: "Automatically install updates without confirmation"。
- ブラウザー識別: フィード取得時に BlindRSS が名乗るブラウザー、または入力したカスタム User-Agent 文字列。実際の文字列は下に表示されます。未知のクライアントを拒むサイトでは重要です。
- Video Search: "Enable adult sites in Video Search"。既定ではオフです。

## Settings: CAPTCHA Solving {#settings-captcha}

インポートした Cookie でも越えられない CAPTCHA を返すサイトのための、任意参加・有料・最後の手段です。

"Enable CAPTCHA solving service" でオンにし、API キーのフィールドには解決サービスのアカウントキーを入れます。解決ごとに料金がかかるため、既定ではオフで、ほかのすべてが失敗した後だけ試されます。

まずサイト Cookie のインポートを試してください。無料で、ほとんどのケースを解決します。

## オンラインアカウントとプロバイダー {#providers}

BlindRSS は購読を自身で保持することも、ホスト型アカウントから読むこともできます。Settings、Provider で選びます。

- Local: 購読はこのマシン上の BlindRSS 自身のデータベースにあります。どこにも同期されません。
- Miniflux: Miniflux サーバーのアドレスと、Miniflux アカウント設定の API キーが必要です。
- Inoreader: Inoreader 開発者ページの app ID と app key、続いてサインイン用の Authorize ボタンが必要です。
- The Old Reader: アカウントのメールアドレスとパスワードが必要です。
- BazQux: アカウントのメールアドレスとパスワードが必要です。

ホスト型プロバイダーでは、既読状態、購読、カテゴリーはアカウントのものなので、同じアカウントでサインインしている別デバイスにも追随します。一部のプロバイダーはカテゴリーを一つのフラットなリストに保つため、BlindRSS は保存されない入れ子を提供する代わりにその旨を示します。

## 通知 {#notifications}

BlindRSS は Settings、Notifications に従って新しい記事の到着時にシステム通知を出します。

- 通知は完全にオフにできます。
- テキストにはフィード名を含められます。
- 上限は更新ごとの到着数を制限し、上限到達時には任意で要約通知を出します。
- 個々のフィードは Settings の Exclude Feeds、またはフィードのコンテキストメニューの "Notifications for This Feed" から除外できます。
- Filter Rule は一致した記事の通知を抑制できます。

これとは別に Announcements は、選んだイベントを NVDA または JAWS 自身のインターフェイスと点字を通じてスクリーンリーダーへ直接読み上げます。システム通知が通らない場合にも届きます。

## 記事の翻訳 {#translation}

Settings、Translate で翻訳を有効にすると、設定した AI サービスを使って、記事テキストを読みながら対象言語へ翻訳します。

翻訳は必要時に行われキャッシュされるため、記事を再読しても二重に料金はかかりません。インターネット接続と、選んだサービス用の自分の API キーが必要です。

アプリケーションインターフェイスは独自のカタログにより別途翻訳されます。インターフェイス言語を参照してください。

## サイト Cookie のインポート {#site-cookies}

一部のサイトは、通常 Cloudflare の "checking your browser" チャレンジのようなブラウザー検証ページをコンテンツの前に置きます。そのようなサイトは、実際のブラウザーで既にチャレンジを通過したセッションにしか応答しないため、BlindRSS 単独では取得できません。

Tools、Import Site Cookies はそのセッションを渡します。

1. Web ブラウザーでサイトを開き、読み込み完了まで待ちます。
2. cookies.txt ブラウザー拡張機能で Cookie を cookies.txt ファイルへエクスポートします。Chrome ベースのブラウザーでは、ダイアログに "Get cookies.txt LOCALLY" へのリンクがあります。
3. ダイアログでエクスポートしたファイルを選びます。
4. 下のフィールドにブラウザーの User-Agent 文字列を貼り付けます。Web で "what is my user agent" を検索すると表示されます。Cloudflare には Cookie が発行された User-Agent と完全に同じものが必要なので、これは重要です。

Firefox 系ブラウザーにはワンクリックの方法があります。"Import from Browser" が Cookie データベースを直接読みます。Chromium ベースのブラウザーは Cookie を暗号化するため、拡張機能が必要です。

## キーボードショートカット {#keyboard-shortcuts}

Tools、Keyboard Shortcuts は BlindRSS のすべてのコマンドをカテゴリー別に現在のキーとともに一覧にし、任意のキーを変更できます。

- コマンドを選び Change Shortcut を選択します。キャプチャダイアログが次に押すキーの組み合わせを記録します。
- Remove Shortcut はコマンドを未割り当てにします。メニューからは引き続き使えます。
- Reset All to Defaults は出荷時のキーを復元します。

ショートカットはメニューアクセラレーターより先にディスパッチされ、プレーヤーウィンドウにフォーカスがあるときも含めウィンドウ全体で動作します。キーボード経路は、メニュー経路が無音の箇所で自身を通知します。変更は設定とともに保存され、更新後も残ります。

## 既定のキーボードショートカット {#shortcuts-reference}

フィード:

- Ctrl+N: Add Feed。
- F5: Refresh Feeds。Shift+F5: Stop Refresh。Ctrl+F5: 選択したフィードを更新。
- F2: Edit Feed または Category。
- Ctrl+Shift+R: Mark All Items as Read。
- Ctrl+Shift+F: Find a Podcast or RSS Feed。

記事とビュー:

- Ctrl+D: Favorites に追加または削除。
- Backspace: 既読・未読を切り替え。Delete: 削除。Shift+Delete: 確認せずに削除。
- Ctrl+E: 検索フィールドへフォーカス。
- Ctrl+Shift+H: リッチな記事全文ビュー。
- Ctrl+1 から Ctrl+3: すべて、未読、既読。Ctrl+4 から Ctrl+6: メディアあり・なし、メディアあり、メディアなし。

プレーヤー:

- Ctrl+P: 再生または一時停止。Ctrl+S: 停止。Ctrl+Shift+P: プレーヤーを表示または非表示。
- Ctrl+Left と Ctrl+Right: シーク。Ctrl+Up と Ctrl+Down: 音量。
- Ctrl+Shift+U、Ctrl+Shift+D、Ctrl+Shift+N: 速く、遅く、通常。
- Ctrl+Shift+E: イコライザー。
- Ctrl+Shift+C: 再生キュー。Ctrl+Shift+T と Ctrl+Shift+V: 次と前。

アプリケーション:

- F1: 使用中のものの節で開くこのガイド。
- Ctrl+comma: Settings。
- Ctrl+Shift+A: 実行中のバージョンを通知。
- Ctrl+X、Ctrl+C、Ctrl+V、Ctrl+A: 切り取り、コピー、貼り付け、すべて選択。

ここにないコマンドは出荷時には未割り当てで、Tools、Keyboard Shortcuts で任意のキーを与えられます。

## インターフェイス言語 {#language}

BlindRSS のインターフェイスは 15 言語に翻訳されています。Settings、General で一つを選ぶか、システム言語に従わせます。変更は再起動時に有効になります。

翻訳はアプリケーションリリースと同時だけでなく、その間にも配信されるため、修正された翻訳は新バージョンを待たずに届きます。

このガイドも、対応する翻訳済みガイドがあれば同じ言語に従い、なければ英語に戻ります。

## トレイアイコンとメディアキー {#tray}

BlindRSS はシステムトレイに常駐できます。Settings、General で、ウィンドウを閉じたときにトレイへ送るか、最小化時に送るか、そこで開始するかを決めます。

トレイアイコンには再生操作があり、メインウィンドウを再び開けます。キーボードのメディアキー（再生/一時停止、停止、次、前）は、BlindRSS のプレーヤーをシステム全体で制御します。

## デスクトップショートカットの追加 {#desktop-shortcuts}

File、Add Shortcuts は、デスクトップ、Start Menu、タスクバーに BlindRSS のショートカットを作成します。必要なものにチェックを付けて OK を選ぶと、それぞれの結果が報告されます。

Start Menu の項目は、Windows がアプリケーションの通知表示前に要求するものでもあるため、別の方法で BlindRSS を起動する場合にも置く価値があります。

## 更新の確認 {#updates}

Help、Check for Updates は新しいバージョンがあるかを確認し、インストールを提案します。

各更新は適用前に検証されます。SHA-256 は公開済みマニフェストと一致しなければならず、Windows では Authenticode 署名も有効でなければなりません。どちらかの確認に失敗した更新はインストールされません。

Settings、General の "Check for updates on startup" はこれを自動実行し、Settings、Advanced の "Automatically install updates without confirmation" は尋ねずに適用します。設定、データベース、ダウンロードは更新によって変更されません。

## バージョンを通知 {#version}

Help、Announce Version（Ctrl+Shift+A）は、実行中の BlindRSS バージョンをスクリーンリーダーへ直接読み上げます。

スクリーンリーダー自身の "report application version" コマンドは実行ファイルのバージョンリソースを読みます。インストール済みビルドでは機能しますが、ソースから BlindRSS を実行すると Python のバージョンを報告します。このコマンドならどちらの場合も正しい答えになります。

## BlindRSS について {#about}

Help、About には、バージョン、ライセンス、GitHub プロフィール、リポジトリ、変更履歴へのリンクが表示されます。

BlindRSS は MIT ライセンスです。許可を求めずに、使用、変更、再配布、ディストリビューションのリポジトリ向けパッケージ化ができます。

## このヘルプウィンドウを使う {#help-window}

このウィンドウは、ガイド用のシンプルで完全にキーボードアクセシブルなリーダーです。

- 目次リストにはすべての節があります。矢印キーで移動します。節を選ぶとテキストがそこへジャンプし、タイトルを通知します。
- テキスト領域は読み取り専用で選択可能なので、スクリーンリーダーで行ごとに読め、コピーできます。
- Ctrl+F で検索ボックスへ移動します。語を入力して Enter を押すと次の出現箇所へジャンプします。
- F3 は次の出現箇所、Shift+F3 は前を探します。検索は折り返します。
- Tab と Shift+Tab で検索ボックス、目次リスト、テキストを移動します。
- Escape でウィンドウを閉じます。

BlindRSS のどこからでも F1 を押すと、使用中のもの（フォーカス中のコントロール、アクティブなダイアログ、強調表示されたメニュー項目、またはプレーヤー）の節でこのウィンドウを開きます。該当する節がない場合、ガイドは先頭で開きます。

ガイドは、翻訳が存在する場合は BlindRSS のインターフェイス言語で表示され、それ以外では英語で表示されます。

## トラブルシューティング {#troubleshooting}

フィードが更新を停止した。Feeds with Errors で理由を確認してください。移転したフィードは Feed Properties でアドレスを直す必要があります。ブラウザー確認を求めるサイトにはサイト Cookie のインポートが必要です。

YouTube 動画を再生できない。Settings、YouTube で YouTube Cookie をインポートし、"Play YouTube by downloading first" をオンにしてください。"sign in to confirm you're not a bot" エラーは常に Cookie を意味します。

再生が途切れる。Settings、Media Player でネットワークキャッシュを増やし、実験的で CPU を使う Skip Silence をオフにしてください。

サイトが何も返さない。Settings、Advanced でブラウザー識別を変更してください。未知のクライアントを完全に拒むサイトがあります。

コマンド実行時に何も読み上げない。Settings、Notifications の Announcements を確認してください。各イベントは個別にオン・オフでき、テストボタンがあります。

何かが奇妙に動き、報告したい。Settings、General でデバッグモードをオンにし、問題を再現して、設定とデータの横に書かれた blindrss.log を添付してください。

## サポートとコミュニティ {#support}

バグと機能要望は、github.com/serrebidev/BlindRSS/issues の GitHub issue tracker に投稿してください。

質問、支援、リリースニュースについては、Telegram の SerrebiProjects グループ t.me/SerrebiProjects が最も早く回答を得られる場所です。

翻訳はいつでも歓迎します。対応言語の一つを話し、何かがおかしく読める場合、修正するプルリクエストはほぼ確実に受け入れられます。ファイルの配置方法はリポジトリの locale/README.md を参照してください。このガイドも同様です。翻訳済みのコピーは docs/help/<language>.md に置き、コンテキスト依存ヘルプが機能し続けるよう、{#anchor} マーカーを英語ファイルとまったく同じに保ってください。
