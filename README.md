# トゥールーズ学校IPSマップ v5.1

ブラウザから教育省APIを直接呼ばず、`data/schools.json`だけを読む構成です。

## 使い方
1. このフォルダをGitHubの公開リポジトリにアップロード。
2. GitHub Pagesで公開。
3. `.github/workflows/update-data.yml` が週1回、教育省の公開APIからデータを取得して `data/schools.json` を更新。

ローカルでHTMLを直接開いた場合はJSON取得がブラウザの制約で失敗することがあるため、動作確認用サンプルデータに自動フォールバックします。

## 注意
`data/schools.json`は同梱サンプルです。実データへの初回更新はGitHub Actionsを実行してください。
